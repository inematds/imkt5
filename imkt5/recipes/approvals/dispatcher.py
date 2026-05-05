"""Composite approval gate — roteia por `approval.mode` para o gate certo."""

from __future__ import annotations

from typing import Any, Protocol

from imkt5.recipes.loader import RecipeStage
from imkt5.types.approvals import Approval, ApprovalDecision, ApprovalMode


class AskUserGate(Protocol):
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
    ) -> None: ...


class AskReviewerGate(Protocol):
    async def ask(
        self,
        *,
        tenant_id: str,
        reviewer_role: str,
        run_id: str,
        stage_id: str,
        question: str,
    ) -> None: ...


class AutoReviewGate(Protocol):
    async def evaluate(
        self,
        *,
        tenant_id: str,
        run_id: str,
        stage_id: str,
        artifacts: dict[str, Any],
        criteria: tuple[str, ...],
    ) -> ApprovalDecision: ...


class ApprovalCallback(Protocol):
    async def __call__(
        self, run_id: str, stage_id: str, decision: ApprovalDecision
    ) -> None: ...


class CompositeApprovalGate:
    """Gate que combina os três modos. Recebe os adapters concretos."""

    def __init__(
        self,
        *,
        on_decided: ApprovalCallback,
        user_gate: AskUserGate | None = None,
        reviewer_gate: AskReviewerGate | None = None,
        auto_gate: AutoReviewGate | None = None,
    ) -> None:
        self._on_decided = on_decided
        self._user_gate = user_gate
        self._reviewer_gate = reviewer_gate
        self._auto_gate = auto_gate

    async def request(
        self,
        *,
        run: Any,  # RecipeRun (evita ciclo de import)
        stage: RecipeStage,
        approval: Approval,
        artifacts: dict[str, Any],
    ) -> None:
        mode = approval.mode
        if mode == ApprovalMode.NONE:
            await self._on_decided(run.run_id, stage.id, ApprovalDecision.APPROVED)
            return

        question = self._build_question(stage, artifacts)

        if mode == ApprovalMode.USER:
            if self._user_gate is None:
                raise RuntimeError("user_gate não configurado")
            await self._user_gate.ask(
                tenant_id=run.tenant_id,
                user_id=run.user_id,
                origin_channel=run.origin_channel,
                origin_external_id=run.origin_channel_external_id,
                run_id=run.run_id,
                stage_id=stage.id,
                question=question,
            )
            return

        if mode == ApprovalMode.HUMAN_REVIEWER:
            if self._reviewer_gate is None:
                raise RuntimeError("reviewer_gate não configurado")
            if not approval.reviewer_role:
                raise ValueError("human_reviewer exige reviewer_role")
            await self._reviewer_gate.ask(
                tenant_id=run.tenant_id,
                reviewer_role=approval.reviewer_role,
                run_id=run.run_id,
                stage_id=stage.id,
                question=question,
            )
            return

        if mode == ApprovalMode.AUTO_REVIEWER:
            if self._auto_gate is None:
                raise RuntimeError("auto_gate não configurado")
            decision = await self._auto_gate.evaluate(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                stage_id=stage.id,
                artifacts=artifacts,
                criteria=approval.criteria,
            )
            await self._on_decided(run.run_id, stage.id, decision)
            return

    def _build_question(
        self, stage: RecipeStage, artifacts: dict[str, Any]
    ) -> str:
        return f"Aprovar estágio '{stage.id}'?"
