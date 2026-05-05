"""Connection pool Postgres.

Singleton lazy-initialized. Se `POSTGRES_URL` não estiver configurado,
Database fica desabilitado (callers caem no caminho in-memory).
"""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None

log = logging.getLogger("imkt5.db")


class Database:
    """Wrapper fino do pool asyncpg."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._pool: Any = None

    async def connect(self) -> None:
        if asyncpg is None:
            raise RuntimeError("asyncpg não instalado")
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            log.info("postgres pool conectado: %s", _redact(self._url))

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("pool não inicializado; chame connect()")
        return self._pool


_db: Database | None = None


def get_pool() -> Database | None:
    """Retorna o Database se POSTGRES_URL estiver setado; senão None."""
    global _db
    if _db is not None:
        return _db
    url = os.environ.get("POSTGRES_URL", "").strip()
    if not url:
        return None
    _db = Database(url)
    return _db


def _redact(url: str) -> str:
    # postgresql://user:pass@host:port/db → postgresql://user:***@host:port/db
    import re
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)
