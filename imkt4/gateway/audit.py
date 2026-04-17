"""Audit log persistente. Grava cada ação mutável no Postgres (tabela
audit_log) e — se DB indisponível — em arquivo JSONL como fallback.

Middleware FastAPI registra: método, path, tenant_id, user_id, status,
duração. Ações específicas (approve/reject, config update, dispatch)
acrescentam detalhes via `record_event()`.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

log = logging.getLogger("imkt4.audit")

FALLBACK_FILE = os.environ.get("IMKT4_AUDIT_FALLBACK", "logs/audit.jsonl")


class AuditSink:
    """Async sink — Postgres preferencialmente, JSONL fallback.

    `pg_pool` pode ser um `asyncpg.Pool` OU uma `Database` (com .pool lazy)
    — AuditSink resolve lazy na hora de usar.
    """

    def __init__(self, pg_pool: Any | None = None) -> None:
        self._pool_ref = pg_pool

    def _pool(self):
        if self._pool_ref is None:
            return None
        # Database wrapper tem ._pool (lazy); asyncpg.Pool tem .acquire() direto
        if hasattr(self._pool_ref, "_pool"):
            return getattr(self._pool_ref, "_pool", None)
        if hasattr(self._pool_ref, "acquire"):
            return self._pool_ref
        return None

    async def ensure_schema(self) -> None:
        pool = self._pool()
        if not pool:
            return
        # Reutiliza a tabela audit_log existente (criada para aprovações).
        # Schema: audit_id, tenant_id, user_id, event_type, details, created_at.
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    audit_id   BIGSERIAL PRIMARY KEY,
                    tenant_id  TEXT,
                    user_id    TEXT,
                    event_type TEXT NOT NULL,
                    details    JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log (tenant_id);
            """)

    async def record(
        self,
        *,
        action: str,
        actor_user: str | None = None,
        actor_tenant: str | None = None,
        target: str | None = None,
        http_method: str | None = None,
        http_path: str | None = None,
        http_status: int | None = None,
        duration_ms: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        pool = self._pool()
        if pool:
            try:
                # Empacota tudo em details pra aproveitar o schema existente
                merged_details: dict[str, Any] = dict(detail or {})
                if target:
                    merged_details["target"] = target
                if http_method:
                    merged_details["http_method"] = http_method
                if http_path:
                    merged_details["http_path"] = http_path
                if http_status is not None:
                    merged_details["http_status"] = http_status
                if duration_ms is not None:
                    merged_details["duration_ms"] = duration_ms

                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO audit_log
                        (tenant_id, user_id, event_type, details)
                        VALUES ($1,$2,$3,$4::jsonb)""",
                        actor_tenant, actor_user, action,
                        json.dumps(merged_details, ensure_ascii=False),
                    )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("audit db fail, fallback arquivo: %s", exc)

        # fallback JSONL
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor_user": actor_user,
            "actor_tenant": actor_tenant,
            "action": action,
            "target": target,
            "http_method": http_method,
            "http_path": http_path,
            "http_status": http_status,
            "duration_ms": duration_ms,
            "detail": detail,
        }
        with suppress(Exception):
            os.makedirs(os.path.dirname(FALLBACK_FILE) or ".", exist_ok=True)
            with open(FALLBACK_FILE, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── middleware FastAPI ───────────────────────────────────────────────
def make_audit_middleware(sink: AuditSink):
    async def middleware(request: Request, call_next):
        t0 = time.time()
        actor_user = request.headers.get("X-User-Id")
        actor_tenant = request.headers.get("X-Tenant-Id")
        # tenta extrair tenant_id do path
        if not actor_tenant:
            actor_tenant = (request.path_params or {}).get("tenant_id")

        status = 0
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # só audita métodos mutáveis
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                dur = int((time.time() - t0) * 1000)
                await sink.record(
                    action="http",
                    actor_user=actor_user,
                    actor_tenant=actor_tenant,
                    http_method=request.method,
                    http_path=request.url.path,
                    http_status=status,
                    duration_ms=dur,
                )

    return middleware
