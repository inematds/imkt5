"""Postgres-backed JobsStore.

Mesma interface de `imkt4.gateway.jobs_store.JobsStore` (create, mark_running,
mark_finished, get, recent, _trim) — mas persistente em Postgres.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from imkt4.db.pool import Database
from imkt4.gateway.jobs_store import JobRecord


class PostgresJobsStore:
    """Store de jobs baseado em Postgres. Drop-in replacement de JobsStore."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        job_id: str,
        tenant_id: str,
        user_id: str,
        capability: str | None,
        worker_type: str | None,
        origin_channel: str = "",
        origin_channel_external_id: str = "",
    ) -> JobRecord:
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO jobs
                    (job_id, tenant_id, user_id, required_capability,
                     worker_type, status, origin_channel,
                     origin_channel_external_id)
                VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7)
                ON CONFLICT (job_id) DO NOTHING
                """,
                job_id, tenant_id, user_id, capability, worker_type,
                origin_channel, origin_channel_external_id,
            )
        return JobRecord(
            job_id=job_id, tenant_id=tenant_id, user_id=user_id,
            capability=capability, worker_type=worker_type, status="pending",
            origin_channel=origin_channel,
            origin_channel_external_id=origin_channel_external_id,
        )

    async def mark_running(self, job_id: str, worker_name: str) -> None:
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE jobs
                   SET status='running', worker_name=$2, updated_at=now()
                 WHERE job_id=$1
                """,
                job_id, worker_name,
            )

    async def mark_finished(
        self,
        job_id: str,
        *,
        success: bool,
        output: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        status = "success" if success else "failed"
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE jobs
                   SET status=$2, output=$3, error=$4, progress=1.0, updated_at=now()
                 WHERE job_id=$1
                """,
                job_id, status,
                json.dumps(output or {}, ensure_ascii=False),
                error,
            )

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._db.pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM jobs WHERE job_id = $1", job_id,
            )
        return _row_to_record(row) if row else None

    async def recent(self, limit: int = 50) -> list[JobRecord]:
        async with self._db.pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [_row_to_record(r) for r in rows]

    async def find_orphans(self, *, older_than_seconds: int = 0) -> list[JobRecord]:
        """Jobs que ficaram 'pending' ou 'running' além de `older_than_seconds`.

        Usado no startup pra re-enfileirar jobs que estavam em voo quando o
        gateway caiu.
        """
        async with self._db.pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM jobs
                WHERE status IN ('pending', 'running')
                  AND updated_at < now() - ($1 || ' seconds')::interval
                ORDER BY created_at ASC
                """,
                str(older_than_seconds),
            )
        return [_row_to_record(r) for r in rows]


def _row_to_record(row) -> JobRecord:
    output = row["output"] or {}
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            output = {}
    return JobRecord(
        job_id=str(row["job_id"]),
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        capability=row["required_capability"],
        worker_type=row["worker_type"],
        status=row["status"],
        worker_name=row["worker_name"],
        output=output,
        error=row["error"],
        origin_channel=(row["origin_channel"] or ""),
        origin_channel_external_id=(row["origin_channel_external_id"] or ""),
        created_at=row["created_at"] or datetime.utcnow(),
        updated_at=row["updated_at"] or datetime.utcnow(),
    )
