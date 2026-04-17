"""Aprovações.

Três modos declarados por estágio de receita:

- `user` — solicitante original aprova no canal em que pediu.
- `human_reviewer` — humano designado por papel (`reviewer_role`).
- `auto_reviewer` — agente LLM executa critérios e retorna decisão;
  pode escalonar para humano em caso de `uncertain`.

Log unificado independente do modo — auditoria igual para as três rotas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ApprovalMode(str, Enum):
    NONE = "none"
    USER = "user"
    HUMAN_REVIEWER = "human_reviewer"
    AUTO_REVIEWER = "auto_reviewer"


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"  # auto_reviewer em dúvida; pode escalonar
    EXPIRED = "expired"


class EscalationPolicy(str, Enum):
    NEVER = "never"
    ON_UNCERTAIN = "on_uncertain"
    ALWAYS = "always"


def _default_approval_timeout() -> int:
    """Lê do settings; fallback defensivo se config não carregou."""
    try:
        from imkt4.config import load
        return int(load().approvals.default_timeout_seconds)
    except Exception:  # noqa: BLE001
        return 1800


@dataclass(frozen=True, slots=True)
class Approval:
    """Configuração declarativa de um gate de aprovação (vem da receita)."""

    mode: ApprovalMode = ApprovalMode.NONE
    timeout_seconds: int = field(default_factory=_default_approval_timeout)
    # para human_reviewer
    reviewer_role: str | None = None
    # para auto_reviewer
    reviewer_worker: str = "auto-reviewer"
    criteria: tuple[str, ...] = ()
    escalation: EscalationPolicy = EscalationPolicy.ON_UNCERTAIN


@dataclass(frozen=True, slots=True)
class ApprovalLog:
    """Decisão concreta registrada. Sempre que um gate resolve, uma
    linha aqui. Auditoria por tenant/parent_job."""

    approval_id: str
    tenant_id: str
    parent_job_id: str
    stage_id: str
    mode: ApprovalMode
    decision: ApprovalDecision
    decider: str  # user_id, reviewer_id, ou "auto-reviewer"
    reason: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
