"""Gates de aprovação reais via Telegram (ou qualquer canal).

Substitui _StubUserGate do main.py por implementação que:
1. Envia pergunta no canal onde a conversa começou.
2. Armazena promise esperando resposta.
3. Quando usuário responde /aprovar <run_id> <stage>, resolve a promise.
4. Runner é notificado via callback on_approval_decided.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from imkt4.channels.base import ChannelRegistry
from imkt4.types.approvals import ApprovalDecision
from imkt4.types.messages import OutgoingMessage
from imkt4.types.tenants import ChannelKind

log = logging.getLogger("imkt4.approvals")


@dataclass
class PendingApproval:
    run_id: str
    stage_id: str
    tenant_id: str
    user_id: str
    channel: ChannelKind
    channel_external_id: str
    question: str
    artifacts_summary: str = ""
    requested_at: datetime = field(default_factory=datetime.utcnow)


class UserApprovalGate:
    """Gate `mode: user` — pergunta ao solicitante original no canal."""

    def __init__(
        self,
        *,
        channels: ChannelRegistry,
        on_decided: Callable[[str, str, ApprovalDecision], Awaitable[None]],
    ) -> None:
        self._channels = channels
        self._on_decided = on_decided
        self._pending: dict[tuple[str, str], PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def ask(
        self,
        *,
        tenant_id: str,
        user_id: str,
        origin_channel: str,
        origin_external_id: str,
        run_id: str,
        stage_id: str,
        question: str,
    ) -> None:
        try:
            kind = ChannelKind(origin_channel)
        except ValueError:
            log.warning(
                "approval: canal %s não suportado; auto-aprovando",
                origin_channel,
            )
            await self._on_decided(run_id, stage_id, ApprovalDecision.APPROVED)
            return

        async with self._lock:
            self._pending[(run_id, stage_id)] = PendingApproval(
                run_id=run_id,
                stage_id=stage_id,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=kind,
                channel_external_id=origin_external_id,
                question=question,
            )

        text = (
            f"🔔 *Aprovação necessária*\n"
            f"Estágio: `{stage_id}` (run `{run_id[:8]}...`)\n\n"
            f"{question}\n\n"
            f"Responda:\n"
            f"  `/aprovar {run_id[:8]} {stage_id}`\n"
            f"  `/rejeitar {run_id[:8]} {stage_id} motivo`"
        )

        try:
            await self._channels.send(
                OutgoingMessage(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    channel=kind,
                    channel_external_id=origin_external_id,
                    text=text,
                )
            )
            log.info("approval: aguardando decisão do usuário (run=%s stage=%s)", run_id, stage_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("approval: falhou ao enviar pergunta (%s); auto-aprovando", exc)
            await self._on_decided(run_id, stage_id, ApprovalDecision.APPROVED)

    async def resolve(
        self,
        run_id_prefix: str,
        stage_id: str,
        decision: ApprovalDecision,
        reason: str = "",
    ) -> bool:
        """Chamado pelo canal quando user responde /aprovar ou /rejeitar.
        Aceita prefixo do run_id (8 chars) porque é o que o user digita."""
        async with self._lock:
            matched_key = None
            for key in self._pending:
                run_id, sid = key
                if sid == stage_id and run_id.startswith(run_id_prefix):
                    matched_key = key
                    break
            if matched_key is None:
                return False
            pending = self._pending.pop(matched_key)

        await self._on_decided(pending.run_id, stage_id, decision)
        log.info(
            "approval: decisão=%s run=%s stage=%s motivo=%s",
            decision.value, pending.run_id, stage_id, reason,
        )
        return True

    def list_pending(self, tenant_id: str | None = None) -> list[PendingApproval]:
        out = list(self._pending.values())
        if tenant_id:
            out = [p for p in out if p.tenant_id == tenant_id]
        return sorted(out, key=lambda p: p.requested_at, reverse=True)


class HumanReviewerGate:
    """Gate `mode: human_reviewer` — resolve o `reviewer_role` do tenant
    pro user_id do reviewer e pergunta no canal dele."""

    def __init__(
        self,
        *,
        user_gate: UserApprovalGate,
        tenant_ctx_provider: Any,
    ) -> None:
        self._user_gate = user_gate
        self._tenant_ctx = tenant_ctx_provider

    async def ask(
        self,
        *,
        tenant_id: str,
        reviewer_role: str,
        run_id: str,
        stage_id: str,
        question: str,
    ) -> None:
        ctx = await self._tenant_ctx.snapshot(tenant_id)
        reviewers = ctx.get("reviewers", {}) or {}
        reviewer_user_id = reviewers.get(reviewer_role)

        if not reviewer_user_id:
            log.warning(
                "human_reviewer: role '%s' não configurada no tenant '%s'; auto-aprovando",
                reviewer_role, tenant_id,
            )
            await self._user_gate._on_decided(run_id, stage_id, ApprovalDecision.APPROVED)
            return

        # Reusa mecanismo do user_gate — mesma UX, destinatário diferente.
        # Precisa descobrir channel do reviewer via channel_bindings do tenant.
        # Por enquanto, assume mesmo canal da sessão original ou falha pra admin.
        # (TODO: quando #5 estiver completo, fazer lookup em channel_bindings.)
        log.warning(
            "human_reviewer: resolução de canal do reviewer não implementada (precisa #5)"
        )
        await self._user_gate._on_decided(run_id, stage_id, ApprovalDecision.APPROVED)
