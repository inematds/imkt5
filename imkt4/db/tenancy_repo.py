"""TenancyRepo — resolver channel_bindings no Postgres."""

from __future__ import annotations

from imkt4.db.pool import Database


class TenancyRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def resolve_channel(
        self, *, channel: str, external_id: str,
    ) -> tuple[str, str] | None:
        """Retorna (tenant_id, user_id) pra um (channel, external_id) ou None."""
        async with self._db.pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tenant_id, user_id
                  FROM channel_bindings
                 WHERE channel = $1 AND external_id = $2
                """,
                channel, external_id,
            )
        if row is None:
            return None
        return (row["tenant_id"], row["user_id"])

    async def upsert_channel_binding(
        self, *, tenant_id: str, user_id: str,
        channel: str, external_id: str,
    ) -> None:
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO channel_bindings (tenant_id, user_id, channel, external_id, verified_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (channel, external_id) DO UPDATE
                   SET tenant_id = EXCLUDED.tenant_id,
                       user_id   = EXCLUDED.user_id,
                       verified_at = now()
                """,
                tenant_id, user_id, channel, external_id,
            )

    async def ensure_user(
        self, *, user_id: str, tenant_id: str, display_name: str = "",
    ) -> None:
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, tenant_id, display_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id, tenant_id, display_name or user_id,
            )
