"""Gateway HTTP (FastAPI).

Endpoints:

- POST  /jobs                   — quick dispatch
- GET   /jobs                   — lista jobs recentes (do store in-memory)
- GET   /jobs/{job_id}          — status + output
- POST  /recipes/{name}/run     — executa receita
- GET   /runs/{run_id}          — status de uma run
- POST  /runs/{run_id}/approve  — aprovar um stage
- POST  /runs/{run_id}/reject   — rejeitar
- GET   /workers                — lista workers + health
- GET   /capabilities           — mapeamento cap → workers
- GET   /artifacts/{...}        — serve arquivos de data/artifacts/
- GET   /ui                     — UI web single-page
- GET   /                       — redirect pra /ui
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.gateway.audit import AuditSink, make_audit_middleware
from imkt4.gateway.auth import Principal, current_principal, require
from imkt4.gateway.jobs_store import JobsStore
from imkt4.gateway.web_ui import UI_HTML
from imkt4.recipes.runner import RecipeRunner
from imkt4.tools.run_recipe import StaticRecipeCatalog
from imkt4.types.approvals import ApprovalDecision
from imkt4.types.jobs import Job, JobPriority

from fastapi import Depends


ARTIFACT_ROOT = Path("./data/artifacts").resolve()


def _resolve_pool(pg_pool: Any) -> Any:
    """Destrincha wrapper Database → asyncpg.Pool, ou retorna direto."""
    if pg_pool is None:
        return None
    # Database wrapper tem método pool() que lança se não conectado
    if hasattr(pg_pool, "_pool"):
        return getattr(pg_pool, "_pool", None)
    # asyncpg.Pool tem .acquire()
    if hasattr(pg_pool, "acquire"):
        return pg_pool
    return None


class DispatchRequest(BaseModel):
    tenant_id: str = "demo"
    user_id: str = "u1"
    capability: str | None = None
    worker_type: str | None = None
    payload: dict[str, Any] = {}
    priority: str = "normal"
    origin_channel: str = "web"
    origin_channel_external_id: str = ""


class RunRecipeRequest(BaseModel):
    tenant_id: str = "demo"
    user_id: str = "u1"
    input: dict[str, Any] = {}
    origin_channel: str = "web"
    origin_channel_external_id: str = ""


class ApprovalRequest(BaseModel):
    stage_id: str
    reason: str = ""


class ChatRequest(BaseModel):
    tenant_id: str = "demo"
    user_id: str = "web"
    text: str
    channel: str = "web"                     # telegram | whatsapp | web
    channel_external_id: str = "web-session"


def create_app(
    *,
    registry: CapabilityRegistry,
    runner: RecipeRunner,
    catalog: StaticRecipeCatalog,
    dispatcher: Any,
    tenant_ctx_provider: Any,
    jobs_store: JobsStore | None = None,
    agent: Any | None = None,
    memory: Any | None = None,
    pg_pool: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="imkt4 Gateway", version="0.0.1")

    # CORS liberado pra dev (UI servida pelo mesmo host, mas curl/fetch
    # externos funcionarem)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Audit middleware — grava toda ação mutável (POST/PUT/PATCH/DELETE)
    audit = AuditSink(pg_pool=pg_pool)
    app.middleware("http")(make_audit_middleware(audit))

    store = jobs_store or JobsStore()

    priority_map = {
        "low": JobPriority.LOW,
        "normal": JobPriority.NORMAL,
        "high": JobPriority.HIGH,
    }

    # ── root + UI ──────────────────────────────────────────────────────
    @app.get("/", response_class=RedirectResponse)
    async def root() -> Any:
        return RedirectResponse(url="/ui")

    @app.get("/ui", response_class=HTMLResponse)
    async def ui() -> Any:
        return HTMLResponse(content=UI_HTML)

    # ── jobs ──────────────────────────────────────────────────────────
    @app.post("/jobs")
    async def create_job(req: DispatchRequest) -> dict[str, str]:
        if not req.capability and not req.worker_type:
            raise HTTPException(400, "capability ou worker_type obrigatório")
        job = Job(
            job_id=str(uuid.uuid4()),
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            worker_type=req.worker_type,
            required_capability=req.capability,
            payload=req.payload,
            origin_channel=req.origin_channel,
            origin_channel_external_id=req.origin_channel_external_id,
            priority=priority_map.get(req.priority, JobPriority.NORMAL),
        )
        await store.create(
            job_id=job.job_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            capability=req.capability,
            worker_type=req.worker_type,
        )
        await dispatcher.dispatch(job)
        return {"job_id": job.job_id}

    @app.get("/jobs")
    async def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
        return [_job_rec_dict(r) for r in await store.recent(limit)]

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        r = await store.get(job_id)
        if r is None:
            raise HTTPException(404, f"job não encontrado: {job_id}")
        return _job_rec_dict(r)

    # ── recipes ───────────────────────────────────────────────────────
    @app.post("/recipes/{name}/run")
    async def run_recipe(name: str, req: RunRecipeRequest) -> dict[str, str]:
        try:
            recipe = catalog.get(name)
        except KeyError as exc:
            raise HTTPException(404, f"receita não encontrada: {name}") from exc
        tenant_ctx = await tenant_ctx_provider.snapshot(req.tenant_id)
        run = await runner.start(
            recipe=recipe,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            input=req.input,
            tenant_ctx=tenant_ctx,
            origin_channel=req.origin_channel,
            origin_channel_external_id=req.origin_channel_external_id,
        )
        return {"run_id": run.run_id}

    @app.get("/recipes")
    async def list_recipes() -> list[dict[str, Any]]:
        return [
            {
                "name": r.name,
                "version": r.version,
                "stages": [
                    {"id": s.id, "requires": s.requires, "needs": list(s.needs)}
                    for s in r.stages
                ],
            }
            for r in catalog.all()
        ]

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        try:
            run = runner.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, f"run não encontrada: {run_id}") from exc
        return {
            "run_id": run.run_id,
            "recipe": run.recipe.name,
            "tenant_id": run.tenant_id,
            "finished": run.is_finished(),
            "failed": run.has_failed(),
            "stages": {
                sid: {
                    "status": s.status.value,
                    "job_ids": list(s.job_ids),
                    "error": s.error,
                    "outputs": s.outputs,
                }
                for sid, s in run.stages.items()
            },
        }

    @app.post("/runs/{run_id}/approve")
    async def approve(run_id: str, req: ApprovalRequest) -> dict[str, str]:
        await runner.on_approval_decided(
            run_id, req.stage_id, ApprovalDecision.APPROVED
        )
        return {"status": "ok"}

    @app.post("/runs/{run_id}/reject")
    async def reject(run_id: str, req: ApprovalRequest) -> dict[str, str]:
        await runner.on_approval_decided(
            run_id, req.stage_id, ApprovalDecision.REJECTED
        )
        return {"status": "ok"}

    # ── audit (read-only) ─────────────────────────────────────────────
    @app.get("/audit")
    async def read_audit(
        limit: int = 50,
        tenant_id: str | None = None,
        principal: Principal = Depends(current_principal),
    ) -> list[dict[str, Any]]:
        # só admins veem audit
        if principal.roles == ("anon",):
            # modo aberto: permitir leitura em dev
            pass
        else:
            if not (
                principal.is_admin_global()
                or (tenant_id and principal.is_admin_of(tenant_id))
            ):
                raise HTTPException(403, "audit requer admin")

        # resolve pool lazy (Database wrapper ou asyncpg.Pool direto)
        pool = _resolve_pool(pg_pool)

        if pool is None:
            # lê do jsonl fallback
            import json as _json
            path = "logs/audit.jsonl"
            if not Path(path).exists():
                return []
            lines = Path(path).read_text().strip().split("\n")
            records = [_json.loads(l) for l in lines if l]
            if tenant_id:
                records = [r for r in records if r.get("actor_tenant") == tenant_id]
            return records[-limit:][::-1]

        async with pool.acquire() as conn:
            if tenant_id:
                rows = await conn.fetch(
                    "SELECT audit_id, tenant_id, user_id, event_type, details, created_at "
                    "FROM audit_log WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
                    tenant_id, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT audit_id, tenant_id, user_id, event_type, details, created_at "
                    "FROM audit_log ORDER BY created_at DESC LIMIT $1", limit
                )
            out = []
            for r in rows:
                d = dict(r)
                # details vem como string JSON do asyncpg quando decodificado default
                if isinstance(d.get("details"), str):
                    try:
                        d["details"] = json.loads(d["details"])
                    except Exception:  # noqa: BLE001
                        pass
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
                out.append(d)
            return out

    # ── workers / capabilities ────────────────────────────────────────
    @app.get("/workers")
    async def list_workers() -> list[dict[str, Any]]:
        out = []
        for w in registry.all_workers():
            s = registry.get_status(w.name)
            out.append(
                {
                    "name": w.name,
                    "capabilities": list(w.capabilities),
                    "local": w.local,
                    "priority": w.priority,
                    "endpoint": w.endpoint,
                    "max_concurrent": w.max_concurrent,
                    "health": s.health.value,
                    "in_flight": s.in_flight,
                    "last_error": s.last_error,
                }
            )
        return out

    @app.post("/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        """Agent loop — LLM decide entre responder direto OU disparar job/receita."""
        if agent is None:
            raise HTTPException(503, "agent loop não configurado")
        from imkt4.types.messages import IncomingMessage
        from imkt4.types.tenants import ChannelKind
        try:
            kind = ChannelKind(req.channel)
        except ValueError:
            raise HTTPException(400, f"channel inválido: {req.channel}")
        inc = IncomingMessage(
            tenant_id=req.tenant_id, user_id=req.user_id, channel=kind,
            channel_external_id=req.channel_external_id, text=req.text,
        )
        out = await agent.process_message(inc)
        return {"text": out.text}

    @app.get("/config")
    async def get_config(tenant_id: str | None = None) -> dict[str, Any]:
        """Dump dos defaults carregados. Se tenant_id, aplica overrides."""
        from imkt4.config import load
        s = load()
        if tenant_id:
            s = s.for_tenant(tenant_id)
        return {
            "tenant_id": tenant_id,
            "settings": s.as_dict(),
        }

    @app.get("/capabilities")
    async def list_capabilities() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for w in registry.all_workers():
            for cap in w.capabilities:
                out.setdefault(cap, []).append(w.name)
        return out

    # ── artefatos (serve arquivos de data/artifacts/) ─────────────────
    @app.get("/artifacts/{path:path}")
    async def get_artifact(path: str) -> FileResponse:
        abs_path = (ARTIFACT_ROOT / path).resolve()
        # anti path-traversal
        if not str(abs_path).startswith(str(ARTIFACT_ROOT)):
            raise HTTPException(403, "forbidden")
        if not abs_path.exists() or not abs_path.is_file():
            raise HTTPException(404, "artefato não encontrado")
        return FileResponse(abs_path)

    return app


def _job_rec_dict(r) -> dict[str, Any]:
    return {
        "job_id": r.job_id,
        "tenant_id": r.tenant_id,
        "user_id": r.user_id,
        "capability": r.capability,
        "worker_type": r.worker_type,
        "worker_name": r.worker_name,
        "status": r.status,
        "output": _urls_in_output(r.output),
        "error": r.error,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _urls_in_output(output: dict[str, Any]) -> dict[str, Any]:
    """Converte `file://...data/artifacts/<path>` em `/artifacts/<path>`
    pra UI conseguir carregar no browser."""
    if not output:
        return output
    out = dict(output)
    for k, v in list(out.items()):
        if isinstance(v, str) and v.startswith("file://"):
            s = v[len("file://"):]
            marker = "/data/artifacts/"
            idx = s.find(marker)
            if idx >= 0:
                out[k] = "/artifacts/" + s[idx + len(marker):]
    return out
