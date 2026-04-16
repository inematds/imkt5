"""Capabilities e Workers Registrados.

Cada worker declara uma ou mais capabilities. Quando uma receita (ou
quick dispatch) pede `capability="X"`, o registry devolve a lista de
workers saudáveis ordenada por (`local` primeiro, `priority` maior),
e o runner tenta-os em ordem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WorkerHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RegisteredWorker:
    """Worker conhecido pelo registry (carregado de config + health-check)."""

    name: str
    capabilities: tuple[str, ...]
    endpoint: str
    local: bool = False
    priority: int = 50
    # Health é atualizado periodicamente fora da dataclass (é imutável).
    # Em runtime, o registry mantém um dict name → health separado.
    timeout_seconds: int = 120
    max_concurrent: int = 4


@dataclass(frozen=True, slots=True)
class WorkerStatus:
    """Estado observado do worker. Mutável via substituição atômica no registry."""

    name: str
    health: WorkerHealth = WorkerHealth.UNKNOWN
    last_checked_at: datetime | None = None
    last_error: str | None = None
    in_flight: int = 0
