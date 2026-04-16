"""Matcher — escolhe qual worker atende uma capability.

Regras (em ordem):

1. **Saturação**: workers com `in_flight >= max_concurrent` ficam fora da
   seleção. Usado para respeitar serializadores upstream (ex.: inemaimg
   tem max_concurrent=1 porque serializa internamente na GPU).
2. **Saúde**: HEALTHY primeiro; DEGRADED/UNKNOWN como fallback se
   `allow_degraded=True`.
3. **Local-first**: `local: true` ganha tie-break.
4. **Prioridade**: maior priority vence.
5. **Menor in-flight**: load-balancing entre instâncias da mesma
   capability (ex.: inemaimg-gpu0 vs inemaimg-gpu1).
"""

from __future__ import annotations

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.types.capabilities import RegisteredWorker, WorkerHealth


class NoWorkerAvailable(RuntimeError):
    """Nenhum worker disponível oferece a capability pedida."""


def _sort_key(reg: CapabilityRegistry, w: RegisteredWorker) -> tuple[int, int, int]:
    """Menor é melhor. Preferência: local, prioridade alta, menos in-flight."""
    status = reg.get_status(w.name)
    return (
        0 if w.local else 1,
        -w.priority,
        status.in_flight,
    )


def _has_capacity(reg: CapabilityRegistry, w: RegisteredWorker) -> bool:
    """True se o worker ainda tem slot livre (in_flight < max_concurrent)."""
    status = reg.get_status(w.name)
    return status.in_flight < w.max_concurrent


def select_worker(
    registry: CapabilityRegistry,
    capability: str,
    *,
    allow_degraded: bool = True,
    respect_capacity: bool = True,
) -> RegisteredWorker:
    """Escolhe o melhor worker para `capability` usando política local-first.

    Se `respect_capacity=True` e todos os workers saudáveis estão saturados,
    levanta `NoWorkerAvailable` — o caller decide entre enfileirar ou
    aceitar overload (passando `respect_capacity=False`).
    """
    candidates = registry.candidates(capability)
    if not candidates:
        raise NoWorkerAvailable(
            f"nenhum worker registrado oferece '{capability}'"
        )

    def _filter_capacity(workers: list[RegisteredWorker]) -> list[RegisteredWorker]:
        if not respect_capacity:
            return workers
        return [w for w in workers if _has_capacity(registry, w)]

    healthy = [
        w for w in candidates
        if registry.get_status(w.name).health == WorkerHealth.HEALTHY
    ]
    healthy_open = _filter_capacity(healthy)
    if healthy_open:
        healthy_open.sort(key=lambda w: _sort_key(registry, w))
        return healthy_open[0]

    if allow_degraded:
        degraded = [
            w for w in candidates
            if registry.get_status(w.name).health
            in (WorkerHealth.DEGRADED, WorkerHealth.UNKNOWN)
        ]
        degraded_open = _filter_capacity(degraded)
        if degraded_open:
            degraded_open.sort(key=lambda w: _sort_key(registry, w))
            return degraded_open[0]

    statuses = {
        w.name: (
            registry.get_status(w.name).health.value,
            registry.get_status(w.name).in_flight,
            w.max_concurrent,
        )
        for w in candidates
    }
    raise NoWorkerAvailable(
        f"nenhum worker disponível para '{capability}'; "
        f"estado (health, in_flight, max): {statuses}"
    )
