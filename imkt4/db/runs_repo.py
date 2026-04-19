"""RunsRepo — persiste recipe_runs no Postgres.

Permite que a listagem GET /runs sobreviva restart do gateway.
"""

from __future__ import annotations

import json
from typing import Any

from imkt4.db.pool import Database


def _ser(obj: Any) -> Any:
    """Torna dataclasses/datetimes serializáveis para JSONB."""
    from datetime import datetime
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "value"):  # enum
        return obj.value
    if hasattr(obj, "__dict__"):
        return {k: _ser(v) for k, v in vars(obj).items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_ser(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    return obj


class RunsRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, run) -> None:
        """Grava/atualiza uma RecipeRun no DB. Chamado em transições de status."""
        stages_json = _ser({
            sid: {
                "status": s.status.value,
                "error": s.error,
                "outputs": _ser(s.outputs),
                "job_ids": list(s.job_ids),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for sid, s in run.stages.items()
        })
        async with self._db.pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO recipe_runs
                  (run_id, tenant_id, user_id, recipe_name, recipe_version,
                   input, origin_channel, origin_channel_external_id,
                   finished, failed, stages, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11::jsonb,$12,now())
                ON CONFLICT (run_id) DO UPDATE SET
                  finished = EXCLUDED.finished,
                  failed = EXCLUDED.failed,
                  stages = EXCLUDED.stages,
                  updated_at = now()
                """,
                run.run_id, run.tenant_id, run.user_id,
                run.recipe.name, getattr(run.recipe, "version", 1),
                json.dumps(_ser(run.input), ensure_ascii=False),
                run.origin_channel, run.origin_channel_external_id,
                run.is_finished(), run.has_failed(),
                json.dumps(stages_json, ensure_ascii=False),
                run.created_at,
            )

    async def list(
        self, *, limit: int = 50, tenant_id: str | None = None,
        recipe: str | None = None,
    ) -> list[dict[str, Any]]:
        q = "SELECT * FROM recipe_runs"
        where = []
        args: list[Any] = []
        if tenant_id:
            args.append(tenant_id)
            where.append(f"tenant_id = ${len(args)}")
        if recipe:
            args.append(recipe)
            where.append(f"recipe_name = ${len(args)}")
        if where:
            q += " WHERE " + " AND ".join(where)
        args.append(limit)
        q += f" ORDER BY created_at DESC LIMIT ${len(args)}"

        async with self._db.pool().acquire() as conn:
            rows = await conn.fetch(q, *args)

        out = []
        for r in rows:
            d = dict(r)
            d["run_id"] = str(d["run_id"])
            for k in ("stages", "input"):
                v = d.get(k)
                if isinstance(v, str):
                    try: d[k] = json.loads(v)
                    except Exception: pass  # noqa: BLE001
            for k in ("created_at", "updated_at"):
                if d.get(k) is not None:
                    d[k] = d[k].isoformat()
            out.append(d)
        return out

    async def fail_orphans(self, *, older_than_seconds: int = 60) -> int:
        """Marca como failed runs que ficaram não-terminais além do limite.

        Usado no startup pra zerar runs presas por restart do gateway
        (stages pending/running/awaiting_approval sem ninguém pra avançar).
        Retorna quantas foram reconciliadas.
        """
        async with self._db.pool().acquire() as conn:
            rows = await conn.fetch(
                f"""
                UPDATE recipe_runs
                   SET failed = true, finished = true,
                       updated_at = now(),
                       stages = stages || '{{"_reconciled": "gateway restart"}}'::jsonb
                 WHERE finished = false
                   AND updated_at < now() - ($1 || ' seconds')::interval
                 RETURNING run_id
                """,
                str(older_than_seconds),
            )
        return len(rows)

    async def delete(self, run_id: str) -> bool:
        """Remove run permanentemente do DB. Retorna True se removeu."""
        async with self._db.pool().acquire() as conn:
            result = await conn.execute(
                "DELETE FROM recipe_runs WHERE run_id = $1", run_id,
            )
            # asyncpg devolve 'DELETE N' — parse e retorna True se N>0
            try:
                n = int(result.rsplit(" ", 1)[-1])
                return n > 0
            except (ValueError, IndexError):
                return False

    async def get(self, run_id: str) -> dict[str, Any] | None:
        async with self._db.pool().acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM recipe_runs WHERE run_id = $1::uuid", run_id
            )
        if not r:
            return None
        d = dict(r)
        d["run_id"] = str(d["run_id"])
        for k in ("stages", "input"):
            v = d.get(k)
            if isinstance(v, str):
                try: d[k] = json.loads(v)
                except Exception: pass  # noqa: BLE001
        for k in ("created_at", "updated_at"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        return d
