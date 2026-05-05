"""Memória conversacional com SQLite FTS5 + BM25, multi-tenant.

Inspirado em openpcbot (`src/memory.ts`, keyed por `chat_id`) e no desenho
do Intelecto (FTS5 + BM25, sem embeddings). Diferença crítica: toda linha
carrega `tenant_id` e `user_id`, e toda query filtra por eles. Não existe
"memória global".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite


class MemoryCategory(str, Enum):
    FACT = "fact"
    CONVERSATION = "conversation"
    SOLUTION = "solution"
    PREFERENCE = "preference"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: int
    tenant_id: str
    user_id: str
    content: str
    category: MemoryCategory
    created_at: datetime
    updated_at: datetime


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    category    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_tenant_user
    ON memories(tenant_id, user_id);

CREATE INDEX IF NOT EXISTS idx_memories_category
    ON memories(tenant_id, user_id, category);

-- FTS5: conteúdo indexado; tenant_id/user_id ficam como UNINDEXED pra
-- permitir filtrar resultados antes do MATCH.
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    tenant_id UNINDEXED,
    user_id UNINDEXED,
    content='memories',
    content_rowid='id'
);

-- Triggers de sincronização memories → memories_fts.
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, tenant_id, user_id)
    VALUES (new.id, new.content, new.tenant_id, new.user_id);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tenant_id, user_id)
    VALUES('delete', old.id, old.content, old.tenant_id, old.user_id);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, tenant_id, user_id)
    VALUES('delete', old.id, old.content, old.tenant_id, old.user_id);
    INSERT INTO memories_fts(rowid, content, tenant_id, user_id)
    VALUES (new.id, new.content, new.tenant_id, new.user_id);
END;
"""


class MemoryStore:
    """Store de memória. Instanciar por arquivo de DB, compartilhar entre tenants."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)

    async def init(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(SCHEMA)
            await db.commit()

    async def save(
        self,
        *,
        tenant_id: str,
        user_id: str,
        content: str,
        category: MemoryCategory,
    ) -> int:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                INSERT INTO memories (tenant_id, user_id, content, category)
                VALUES (?, ?, ?, ?)
                """,
                (tenant_id, user_id, content, category.value),
            )
            await db.commit()
            assert cur.lastrowid is not None
            return cur.lastrowid

    async def search(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Full-text search com ranking BM25, escopo restrito ao par (tenant, user)."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT m.id, m.tenant_id, m.user_id, m.content, m.category,
                       m.created_at, m.updated_at
                  FROM memories_fts f
                  JOIN memories m ON m.id = f.rowid
                 WHERE f.memories_fts MATCH ?
                   AND f.tenant_id = ?
                   AND f.user_id   = ?
                 ORDER BY bm25(memories_fts)
                 LIMIT ?
                """,
                (query, tenant_id, user_id, limit),
            )
            rows = await cur.fetchall()
            return [_row_to_entry(r) for r in rows]

    async def recent(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT id, tenant_id, user_id, content, category,
                       created_at, updated_at
                  FROM memories
                 WHERE tenant_id = ? AND user_id = ?
                 ORDER BY created_at DESC
                 LIMIT ?
                """,
                (tenant_id, user_id, limit),
            )
            rows = await cur.fetchall()
            return [_row_to_entry(r) for r in rows]

    async def forget(
        self, *, tenant_id: str, user_id: str, memory_id: int
    ) -> bool:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                DELETE FROM memories
                 WHERE id = ? AND tenant_id = ? AND user_id = ?
                """,
                (memory_id, tenant_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0


def _row_to_entry(r: Any) -> MemoryEntry:
    return MemoryEntry(
        id=r["id"],
        tenant_id=r["tenant_id"],
        user_id=r["user_id"],
        content=r["content"],
        category=MemoryCategory(r["category"]),
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
    )
