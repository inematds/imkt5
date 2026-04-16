"""Contrato de Job.

Todo trabalho pesado do sistema vira um Job. O Gateway cria jobs via duas
rotas:

- **Quick dispatch**: pedido simples, 1 job direto por capability. Sem
  receita, sem parent.
- **Recipe Runner**: uma receita (YAML) gera N jobs, todos com mesmo
  `parent_job_id` e cada um marcado com seu `recipe_stage`.

`worker_type` é opcional — quando ausente, o runner escolhe via
`required_capability` + capability registry (local-first).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"


class JobPriority(int, Enum):
    LOW = 10
    NORMAL = 50
    HIGH = 90


@dataclass(frozen=True, slots=True)
class Job:
    """Pedido de trabalho enfileirado. Imutável após criação."""

    job_id: str
    tenant_id: str
    user_id: str

    # Endereçamento do trabalho — um dos dois deve estar preenchido.
    # `worker_type` é caminho "direto" (quick dispatch sabe quem).
    # `required_capability` é caminho "indireto" (runner resolve via registry).
    worker_type: str | None = None
    required_capability: str | None = None

    payload: dict[str, Any] = field(default_factory=dict)

    # De onde o pedido veio — usado pelo Gateway pra entregar resultado.
    origin_channel: str = ""
    origin_channel_external_id: str = ""

    priority: JobPriority = JobPriority.NORMAL
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Dedupe: pedidos idênticos em sequência retornam mesmo job_id.
    dedupe_key: str | None = None

    # Correlação com receita (None se for quick dispatch).
    parent_job_id: str | None = None
    recipe_name: str | None = None
    recipe_stage: str | None = None
    # Quando fanout_over gera N jobs, cada um tem índice 0..N-1.
    fanout_index: int | None = None

    def __post_init__(self) -> None:
        if not self.worker_type and not self.required_capability:
            raise ValueError(
                "Job precisa de worker_type OU required_capability"
            )


@dataclass(frozen=True, slots=True)
class JobResult:
    """Resultado de um job. Pode ser parcial (progress) ou final."""

    job_id: str
    tenant_id: str
    status: JobStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    progress: float = 0.0
    updated_at: datetime = field(default_factory=datetime.utcnow)
