"""Capability Registry.

Mantém o catálogo de workers conhecidos e seu estado de saúde.
Health-check é assíncrono e não bloqueante — `lookup()` sempre devolve
a melhor opção conhecida naquele momento.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from imkt4.types.capabilities import RegisteredWorker, WorkerHealth, WorkerStatus


class HealthProbe(Protocol):
    async def __call__(self, worker: RegisteredWorker) -> tuple[WorkerHealth, str | None]: ...


async def _default_probe(
    worker: RegisteredWorker,
) -> tuple[WorkerHealth, str | None]:
    """Probe HTTP padrão: GET {endpoint}/health com timeout curto."""
    from imkt4.config import load
    timeout = load().capability_registry.probe_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{worker.endpoint.rstrip('/')}/health")
            if r.status_code == 200:
                return WorkerHealth.HEALTHY, None
            if 500 <= r.status_code < 600:
                return WorkerHealth.DOWN, f"http {r.status_code}"
            return WorkerHealth.DEGRADED, f"http {r.status_code}"
    except httpx.TimeoutException:
        return WorkerHealth.DOWN, "timeout"
    except Exception as exc:  # noqa: BLE001
        return WorkerHealth.DOWN, f"{type(exc).__name__}: {exc}"


class CapabilityRegistry:
    """Registry in-memory. Thread-safe via lock simples."""

    def __init__(self, probe: HealthProbe | None = None) -> None:
        self._workers: dict[str, RegisteredWorker] = {}
        self._status: dict[str, WorkerStatus] = {}
        self._by_capability: dict[str, list[str]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._probe = probe or _default_probe

    # ── registro ──────────────────────────────────────────────────────
    def register(self, worker: RegisteredWorker) -> None:
        if worker.name in self._workers:
            raise ValueError(f"worker já registrado: {worker.name}")
        self._workers[worker.name] = worker
        self._status[worker.name] = WorkerStatus(name=worker.name)
        for cap in worker.capabilities:
            self._by_capability[cap].append(worker.name)

    def unregister(self, name: str) -> None:
        worker = self._workers.pop(name, None)
        if worker is None:
            return
        self._status.pop(name, None)
        for cap in worker.capabilities:
            if name in self._by_capability.get(cap, []):
                self._by_capability[cap].remove(name)

    # ── consulta ──────────────────────────────────────────────────────
    def all_workers(self) -> list[RegisteredWorker]:
        return list(self._workers.values())

    def get_worker(self, name: str) -> RegisteredWorker:
        return self._workers[name]

    def get_status(self, name: str) -> WorkerStatus:
        return self._status[name]

    def candidates(self, capability: str) -> list[RegisteredWorker]:
        """Retorna todos os workers que oferecem `capability` (sem filtrar
        por saúde — isso é tarefa do matcher)."""
        names = self._by_capability.get(capability, [])
        return [self._workers[n] for n in names]

    # ── health ────────────────────────────────────────────────────────
    async def refresh_health(self) -> None:
        """Probe todos os workers em paralelo e atualiza status."""
        tasks = [self._probe_one(w) for w in self._workers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _probe_one(self, worker: RegisteredWorker) -> None:
        health, err = await self._probe(worker)
        async with self._lock:
            cur = self._status.get(worker.name)
            self._status[worker.name] = WorkerStatus(
                name=worker.name,
                health=health,
                last_checked_at=datetime.utcnow(),
                last_error=err,
                in_flight=cur.in_flight if cur else 0,
            )

    # ── contabilidade de concorrência ────────────────────────────────
    async def acquire(self, name: str) -> None:
        async with self._lock:
            s = self._status[name]
            self._status[name] = WorkerStatus(
                name=s.name,
                health=s.health,
                last_checked_at=s.last_checked_at,
                last_error=s.last_error,
                in_flight=s.in_flight + 1,
            )

    async def release(self, name: str) -> None:
        async with self._lock:
            s = self._status[name]
            self._status[name] = WorkerStatus(
                name=s.name,
                health=s.health,
                last_checked_at=s.last_checked_at,
                last_error=s.last_error,
                in_flight=max(0, s.in_flight - 1),
            )

    # ── loader ────────────────────────────────────────────────────────
    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        probe: HealthProbe | None = None,
    ) -> "CapabilityRegistry":
        """Carrega workers de um arquivo YAML no formato:

        workers:
          - name: stable-diffusion-local
            capabilities: [image.generation]
            endpoint: http://localhost:7860
            local: true
            priority: 100
        """
        import yaml

        data = yaml.safe_load(Path(path).read_text())
        reg = cls(probe=probe)
        for w in data.get("workers", []):
            reg.register(
                RegisteredWorker(
                    name=w["name"],
                    capabilities=tuple(w["capabilities"]),
                    endpoint=w["endpoint"],
                    local=bool(w.get("local", False)),
                    priority=int(w.get("priority", 50)),
                    timeout_seconds=int(w.get("timeout_seconds", 120)),
                    max_concurrent=int(w.get("max_concurrent", 4)),
                )
            )
        return reg
