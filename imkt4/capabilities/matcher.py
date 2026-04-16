"""Matcher — escolhe qual worker atende uma capability.

Regra: dentre os que oferecem a capability, pega os saudáveis,
ordena por (local primeiro, priority maior, menos in-flight),
retorna o primeiro. Se nenhum saudável, cai pra DEGRADED. Se nem
isso, levanta exceção.
"""

from __future__ import annotations

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.types.capabilities import RegisteredWorker, WorkerHealth


class NoWorkerAvailable(RuntimeError):
    """Nenhum worker saudável oferece a capability pedida."""


def _sort_key(reg: CapabilityRegistry, w: RegisteredWorker) -> tuple[int, int, int]:
    """Menor é melhor. Preferência: local, prioridade alta, pouco in-flight."""
    status = reg.get_status(w.name)
    return (
        0 if w.local else 1,
        -w.priority,
        status.in_flight,
    )


def select_worker(
    registry: CapabilityRegistry,
    capability: str,
    *,
    allow_degraded: bool = True,
) -> RegisteredWorker:
    """Escolhe o melhor worker para `capability` usando política local-first."""
    candidates = registry.candidates(capability)
    if not candidates:
        raise NoWorkerAvailable(
            f"nenhum worker registrado oferece '{capability}'"
        )

    healthy = [
        w for w in candidates
        if registry.get_status(w.name).health == WorkerHealth.HEALTHY
    ]
    if healthy:
        healthy.sort(key=lambda w: _sort_key(registry, w))
        return healthy[0]

    if allow_degraded:
        degraded = [
            w for w in candidates
            if registry.get_status(w.name).health
            in (WorkerHealth.DEGRADED, WorkerHealth.UNKNOWN)
        ]
        if degraded:
            degraded.sort(key=lambda w: _sort_key(registry, w))
            return degraded[0]

    statuses = {
        w.name: registry.get_status(w.name).health.value for w in candidates
    }
    raise NoWorkerAvailable(
        f"nenhum worker saudável para '{capability}'; estado: {statuses}"
    )
