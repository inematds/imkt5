"""JobsStore em memória.

Para a UI e API poderem consultar status de jobs individuais (quick
dispatch). Guarda os últimos N jobs; mais velho é descartado.

Em produção, substituir por Postgres — contrato igual.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class JobRecord:
    job_id: str
    tenant_id: str
    user_id: str
    capability: str | None
    worker_type: str | None
    status: str = "pending"   # pending | running | success | failed
    worker_name: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class JobsStore:
    def __init__(self, max_size: int = 500) -> None:
        self._data: OrderedDict[str, JobRecord] = OrderedDict()
        self._max = max_size

    def create(
        self,
        *,
        job_id: str,
        tenant_id: str,
        user_id: str,
        capability: str | None,
        worker_type: str | None,
    ) -> JobRecord:
        rec = JobRecord(
            job_id=job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            capability=capability,
            worker_type=worker_type,
            status="pending",
        )
        self._data[job_id] = rec
        self._trim()
        return rec

    def mark_running(self, job_id: str, worker_name: str) -> None:
        r = self._data.get(job_id)
        if r is None:
            return
        r.status = "running"
        r.worker_name = worker_name
        r.updated_at = datetime.utcnow()

    def mark_finished(
        self,
        job_id: str,
        *,
        success: bool,
        output: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        r = self._data.get(job_id)
        if r is None:
            return
        r.status = "success" if success else "failed"
        r.output = output or {}
        r.error = error
        r.updated_at = datetime.utcnow()

    def get(self, job_id: str) -> JobRecord | None:
        return self._data.get(job_id)

    def recent(self, limit: int = 50) -> list[JobRecord]:
        return list(self._data.values())[-limit:][::-1]

    def _trim(self) -> None:
        while len(self._data) > self._max:
            self._data.popitem(last=False)
