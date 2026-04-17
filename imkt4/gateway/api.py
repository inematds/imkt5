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
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.gateway.admin_ui import ADMIN_HTML
from imkt4.gateway.audit import AuditSink, make_audit_middleware
from imkt4.gateway.auth import Principal, current_principal, require
from imkt4.gateway.jobs_store import JobsStore
from imkt4.gateway.web_ui import UI_HTML
from imkt4.recipes.runner import RecipeRunner
from imkt4.tools.run_recipe import StaticRecipeCatalog
from imkt4.types.approvals import ApprovalDecision
from imkt4.types.jobs import Job, JobPriority

from fastapi import Depends, Request


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
    tenancy_repo: Any | None = None,
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

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_ui() -> Any:
        # HTML da SPA — público. Endpoints /admin/<resto> exigem admin-global.
        return HTMLResponse(content=ADMIN_HTML)

    async def _require_admin(request: Any) -> Principal:
        p = await current_principal(request, request.headers.get("authorization"))
        if p.roles == ("anon",):
            raise HTTPException(401, "admin exige autenticação")
        if not p.is_admin_global() and not any(
            r.startswith("admin-tenant") for r in p.roles
        ):
            raise HTTPException(403, "requer admin-global ou admin-tenant")
        return p

    # ── admin: config/workers/recipes (textual) ──────────────────────
    @app.get("/admin/config/defaults", response_class=HTMLResponse)
    async def admin_cfg_get(request: Request) -> Any:
        await _require_admin(request)
        p = Path("config/defaults.yaml")
        if not p.exists():
            return HTMLResponse("# sem defaults.yaml\n", media_type="text/plain")
        return HTMLResponse(p.read_text(), media_type="text/plain")

    @app.put("/admin/config/defaults")
    async def admin_cfg_put(request: Request) -> dict[str, str]:
        await _require_admin(request)
        body = (await request.body()).decode()
        Path("config/defaults.yaml").write_text(body)
        return {"status": "ok"}

    @app.get("/admin/config/tenant/{tenant_id}", response_class=HTMLResponse)
    async def admin_tcfg_get(tenant_id: str, request: Request) -> Any:
        await _require_admin(request)
        p = Path(f"profiles/{tenant_id}/config.yaml")
        if not p.exists():
            return HTMLResponse("# sem config.yaml pra este tenant\n", media_type="text/plain")
        return HTMLResponse(p.read_text(), media_type="text/plain")

    @app.put("/admin/config/tenant/{tenant_id}")
    async def admin_tcfg_put(tenant_id: str, request: Request) -> dict[str, str]:
        await _require_admin(request)
        body = (await request.body()).decode()
        folder = Path(f"profiles/{tenant_id}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.yaml").write_text(body)
        return {"status": "ok"}

    @app.post("/admin/workers/append")
    async def admin_workers_append(request: Request) -> dict[str, str]:
        await _require_admin(request)
        body = (await request.body()).decode().rstrip()
        path = Path("config/workers.yaml")
        existing = path.read_text()
        if not existing.endswith("\n"):
            existing += "\n"
        path.write_text(existing + "\n" + body + "\n")
        return {"status": "ok"}

    @app.get("/admin/recipes")
    async def admin_recipes_list(request: Request) -> list[str]:
        await _require_admin(request)
        folder = Path("recipes")
        if not folder.exists():
            return []
        return sorted([p.stem for p in folder.glob("*.yaml")])

    @app.get("/admin/recipes/{name}", response_class=HTMLResponse)
    async def admin_recipe_get(name: str, request: Request) -> Any:
        await _require_admin(request)
        if "/" in name or ".." in name:
            raise HTTPException(400, "nome inválido")
        p = Path(f"recipes/{name}.yaml")
        if not p.exists():
            raise HTTPException(404, f"recipe não encontrada: {name}")
        return HTMLResponse(p.read_text(), media_type="text/plain")

    @app.put("/admin/recipes/{name}")
    async def admin_recipe_put(name: str, request: Request) -> dict[str, str]:
        await _require_admin(request)
        if "/" in name or ".." in name:
            raise HTTPException(400, "nome inválido")
        # valida YAML antes de gravar
        body = (await request.body()).decode()
        try:
            import yaml
            parsed = yaml.safe_load(body)
            if not isinstance(parsed, dict) or "stages" not in parsed:
                raise ValueError("receita precisa ter 'stages'")
        except Exception as exc:
            raise HTTPException(400, f"YAML inválido: {exc}") from exc
        Path(f"recipes/{name}.yaml").write_text(body)
        # recarrega catálogo em memória — o catálogo expõe um método reload?
        if hasattr(catalog, "reload"):
            try:
                catalog.reload()
            except Exception as exc:  # noqa: BLE001
                log_msg = f"reload recipes: {exc}"
                print(log_msg)
        return {"status": "ok"}

    # ── admin: channels (whitelist de bindings) ──────────────────────
    class ChannelBindingReq(BaseModel):
        kind: str          # telegram|whatsapp|web
        external_id: str
        tenant_id: str
        user_id: str = ""

    @app.get("/admin/channels")
    async def admin_channels_list(request: Request, kind: str | None = None) -> list[dict]:
        await _require_admin(request)
        if tenancy_repo is None:
            raise HTTPException(503, "TenancyRepo não configurado (Postgres offline?)")
        rows = await tenancy_repo.list_bindings(channel=kind)
        out = []
        for r in rows:
            out.append({
                "kind": r["channel"],
                "external_id": r["external_id"],
                "tenant_id": r["tenant_id"],
                "user_id": r["user_id"],
                "created_at": r["verified_at"].isoformat() if r.get("verified_at") else None,
            })
        return out

    @app.post("/admin/channels")
    async def admin_channels_add(request: Request, req: ChannelBindingReq) -> dict[str, str]:
        await _require_admin(request)
        if tenancy_repo is None:
            raise HTTPException(503, "TenancyRepo não configurado")
        if req.user_id:
            await tenancy_repo.ensure_user(
                user_id=req.user_id, tenant_id=req.tenant_id, display_name=req.user_id,
            )
        await tenancy_repo.upsert_channel_binding(
            tenant_id=req.tenant_id,
            user_id=req.user_id or f"{req.kind}-{req.external_id}",
            channel=req.kind,
            external_id=req.external_id,
        )
        return {"status": "ok"}

    @app.delete("/admin/channels/{kind}/{external_id}")
    async def admin_channels_del(kind: str, external_id: str, request: Request) -> dict[str, str]:
        await _require_admin(request)
        if tenancy_repo is None:
            raise HTTPException(503, "TenancyRepo não configurado")
        ok = await tenancy_repo.delete_binding(channel=kind, external_id=external_id)
        if not ok:
            raise HTTPException(404, "binding não encontrado")
        return {"status": "ok"}

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

    # ── delivery: download bundle zip de uma recipe run ──────────────
    @app.get("/runs/{run_id}/bundle.zip")
    async def download_bundle(run_id: str) -> Any:
        try:
            run = runner.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(404, f"run não encontrada: {run_id}") from exc

        # Coleta todos os paths de artefatos dos outputs dos stages
        from io import BytesIO
        import zipfile
        from urllib.parse import urlparse

        def _iter_urls(obj: Any):
            if isinstance(obj, str):
                s = obj
                if s.startswith(("file://", "/artifacts/")) or s.startswith(("http://", "https://")):
                    yield s
            elif isinstance(obj, dict):
                for v in obj.values():
                    yield from _iter_urls(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _iter_urls(v)

        def _resolve_local_path(url: str) -> Path | None:
            if url.startswith("file://"):
                return Path(url[len("file://"):])
            if url.startswith("/artifacts/"):
                root = os.environ.get("IMKT4_ARTIFACT_ROOT", str(ARTIFACT_ROOT))
                return Path(root) / url[len("/artifacts/"):]
            return None

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # manifest.json com resumo da run
            manifest: dict[str, Any] = {
                "run_id": run_id,
                "recipe": run.recipe.name,
                "tenant_id": run.tenant_id,
                "stages": {},
            }
            for sid, state in run.stages.items():
                manifest["stages"][sid] = {
                    "status": state.status.value,
                    "output": state.output if state.outputs else None,
                }
                for url in _iter_urls(state.output if state.outputs else None):
                    path = _resolve_local_path(url)
                    if path and path.exists():
                        arc = f"{sid}/{path.name}"
                        try:
                            zf.write(path, arc)
                        except Exception:  # noqa: BLE001
                            pass
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))

        from fastapi.responses import Response
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=run-{run_id[:8]}.zip"},
        )

    # ── delivery: publish manual (disparo de job platform.*) ─────────
    class PublishReq(BaseModel):
        platform: str  # instagram|youtube|tiktok|facebook|threads|linkedin
        artifact_url: str
        caption: str = ""
        tenant_id: str
        user_id: str = "u1"

    @app.post("/runs/{run_id}/publish")
    async def publish_run(run_id: str, req: PublishReq) -> dict[str, Any]:
        # Dispara um job platform.<req.platform>. Se worker não existe,
        # retorna 503 com lista de platforms disponíveis.
        capability = f"platform.{req.platform}"
        available = []
        for w in registry.all_workers():
            for cap in w.capabilities:
                if cap.startswith("platform."):
                    available.append(cap.split(".", 1)[1])
        if capability not in [f"platform.{p}" for p in available]:
            raise HTTPException(
                503,
                f"platform '{req.platform}' sem worker registrado. "
                f"disponíveis: {available}"
            )
        job = Job(
            job_id=str(uuid.uuid4()),
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            required_capability=capability,
            payload={"artifact_url": req.artifact_url, "caption": req.caption,
                     "run_id": run_id},
            origin_channel="publish",
            origin_channel_external_id=run_id,
        )
        await store.create(
            job_id=job.job_id, tenant_id=req.tenant_id, user_id=req.user_id,
            capability=capability, worker_type=None,
        )
        await dispatcher.dispatch(job)
        return {"job_id": job.job_id, "status": "dispatched"}

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
