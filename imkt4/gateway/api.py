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
from imkt4.gateway.recipes_ui import RECIPES_UI_HTML
from imkt4.gateway.runs_ui import RUNS_UI_HTML
from imkt4.gateway.workers_ui import WORKERS_UI_HTML
from imkt4.gateway.chat_ui import CHAT_UI_HTML
from imkt4.gateway.audit import AuditSink, make_audit_middleware
from imkt4.gateway.auth import Principal, current_principal
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


class ChannelBindingReq(BaseModel):
    kind: str          # telegram|whatsapp|web
    external_id: str
    tenant_id: str
    user_id: str = ""


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
        return HTMLResponse(
            content=UI_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_ui() -> Any:
        # HTML da SPA — público. Endpoints /admin/<resto> exigem admin-global.
        return HTMLResponse(
            content=ADMIN_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/recipes-ui", response_class=HTMLResponse)
    async def recipes_ui() -> Any:
        return HTMLResponse(
            content=RECIPES_UI_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/runs-ui", response_class=HTMLResponse)
    async def runs_ui() -> Any:
        return HTMLResponse(
            content=RUNS_UI_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/workers-ui", response_class=HTMLResponse)
    async def workers_ui_page() -> Any:
        return HTMLResponse(
            content=WORKERS_UI_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/chat-ui", response_class=HTMLResponse)
    async def chat_ui_page() -> Any:
        return HTMLResponse(
            content=CHAT_UI_HTML,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    async def _require_admin(request: Any) -> Principal:
        p = await current_principal(request, request.headers.get("authorization"))
        if p.roles == ("anon",):
            raise HTTPException(401, "admin exige autenticação")
        if not p.is_admin_global() and not any(
            r.startswith("admin-tenant") for r in p.roles
        ):
            raise HTTPException(403, "requer admin-global ou admin-tenant")
        return p

    async def _require_user(request: Any, tenant_id: str | None = None) -> Principal:
        """Exige autenticação + enforcement de tenant.

        Papéis aceitos: admin-global · admin-tenant:X · user:X · reviewer:X.
        Se `tenant_id` é informado, verifica que o principal pode agir naquele
        tenant. Modo anônimo é aceito quando IMKT4_AUTH_REQUIRED != 1 — isso
        mantém o gateway utilizável em dev.
        """
        p = await current_principal(request, request.headers.get("authorization"))
        # Em dev (sem IMKT4_AUTH_REQUIRED=1), anon pode tudo — é o padrão atual.
        if p.roles == ("anon",):
            import os as _os
            if _os.environ.get("IMKT4_AUTH_REQUIRED", "0") != "1":
                return p
            raise HTTPException(401, "bearer token obrigatório")
        # tem token: valida tenant boundary
        if tenant_id and not p.can_act_in_tenant(tenant_id):
            raise HTTPException(403, f"sem permissão no tenant {tenant_id}")
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
    async def admin_channels_add(req: ChannelBindingReq, request: Request) -> dict[str, str]:
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
    async def create_job(req: DispatchRequest, request: Request) -> dict[str, str]:
        await _require_user(request, tenant_id=req.tenant_id)
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
    async def list_jobs(
        limit: int = 50,
        worker_name: str | None = None,
        capability: str | None = None,
        tenant_id: str | None = None,
        status: str | None = None,
        origin_channel: str | None = None,
        origin_external_id: str | None = None,
    ) -> list[dict[str, Any]]:
        any_filter = (worker_name or capability or tenant_id or status
                      or origin_channel or origin_external_id)
        raw_limit = limit * 4 if any_filter else limit
        recs = await store.recent(raw_limit)
        filtered = []
        for r in recs:
            if worker_name and r.worker_name != worker_name:
                continue
            if capability and r.capability != capability:
                continue
            if tenant_id and r.tenant_id != tenant_id:
                continue
            if status and r.status != status:
                continue
            if origin_channel and getattr(r, "origin_channel", None) != origin_channel:
                continue
            if origin_external_id and getattr(r, "origin_channel_external_id", None) != origin_external_id:
                continue
            filtered.append(r)
            if len(filtered) >= limit:
                break
        return [_job_rec_dict(r) for r in filtered]

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        r = await store.get(job_id)
        if r is None:
            raise HTTPException(404, f"job não encontrado: {job_id}")
        return _job_rec_dict(r)

    # ── recipes ───────────────────────────────────────────────────────
    @app.post("/recipes/{name}/run")
    async def run_recipe(name: str, req: RunRecipeRequest, request: Request) -> dict[str, str]:
        await _require_user(request, tenant_id=req.tenant_id)
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

    @app.get("/runs")
    async def list_runs(
        limit: int = 50, tenant_id: str | None = None, recipe: str | None = None,
    ) -> list[dict[str, Any]]:
        """Últimas runs, mais recentes primeiro. Junta memória + DB
        (DB sobrevive restart, memória tem dados mais frescos)."""
        runs = runner.list_runs(limit=limit * 4 if recipe else limit, tenant_id=tenant_id)
        if recipe:
            runs = [r for r in runs if r.recipe.name == recipe][:limit]

        # Se existe RunsRepo, mescla com registros do DB (evita duplicar
        # os que já estão em memória).
        repo = getattr(runner, "_runs_repo", None)
        if repo is not None:
            try:
                db_rows = await repo.list(limit=limit * 2, tenant_id=tenant_id, recipe=recipe)
                in_mem_ids = {r.run_id for r in runs}
                out = []
                for r in runs:
                    stage_counts: dict[str, int] = {}
                    for s in r.stages.values():
                        stage_counts[s.status.value] = stage_counts.get(s.status.value, 0) + 1
                    status = "failed" if r.has_failed() else ("running" if not r.is_finished() else "success")
                    out.append({
                        "run_id": r.run_id, "recipe": r.recipe.name,
                        "tenant_id": r.tenant_id, "user_id": r.user_id,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "status": status, "stage_counts": stage_counts,
                        "total_stages": len(r.stages),
                        "input": r.input or {},  # preview do input na lista
                    })
                for row in db_rows:
                    if row["run_id"] in in_mem_ids:
                        continue
                    stages = row.get("stages") or {}
                    counts: dict[str, int] = {}
                    for sid, sd in stages.items():
                        # Ignora chaves de metadata (ex.: "_reconciled")
                        if sid.startswith("_") or not isinstance(sd, dict):
                            continue
                        st = sd.get("status", "?")
                        counts[st] = counts.get(st, 0) + 1
                    status = "failed" if row.get("failed") else ("success" if row.get("finished") else "running")
                    out.append({
                        "run_id": row["run_id"], "recipe": row.get("recipe_name"),
                        "tenant_id": row.get("tenant_id"), "user_id": row.get("user_id"),
                        "created_at": row.get("created_at"),
                        "status": status, "stage_counts": counts,
                        "total_stages": len(stages),
                        "input": row.get("input") or {},
                    })
                # Ordena por created_at desc e aplica limit
                out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
                return out[:limit]
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger("imkt4.api").warning("runs_repo.list falhou: %s", exc)
        out = []
        for r in runs:
            stage_counts: dict[str, int] = {}
            for s in r.stages.values():
                stage_counts[s.status.value] = stage_counts.get(s.status.value, 0) + 1
            overall = "success"
            if r.has_failed():
                overall = "failed"
            elif not r.is_finished():
                overall = "running"
            out.append({
                "run_id": r.run_id,
                "recipe": r.recipe.name,
                "tenant_id": r.tenant_id,
                "user_id": r.user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status": overall,
                "stage_counts": stage_counts,
                "total_stages": len(r.stages),
                "input": r.input or {},
            })
        return out

    async def _load_prev_for_rerun(run_id: str):
        """Retorna (recipe, tenant_id, user_id, input, origin_channel,
        origin_channel_external_id) — da memória ou do Postgres."""
        try:
            prev = runner.get_run(run_id)
            return (prev.recipe, prev.tenant_id, prev.user_id,
                    dict(prev.input), prev.origin_channel,
                    prev.origin_channel_external_id)
        except KeyError:
            pass
        repo = getattr(runner, "_runs_repo", None)
        if repo is None:
            raise HTTPException(404, f"run não encontrada: {run_id}")
        row = await repo.get(run_id)
        if not row:
            raise HTTPException(404, f"run não encontrada: {run_id}")
        try:
            recipe = catalog.get(row.get("recipe_name", ""))
        except KeyError as exc:
            raise HTTPException(
                410, f"receita '{row.get('recipe_name')}' não existe mais"
            ) from exc
        return (recipe, row.get("tenant_id"), row.get("user_id"),
                dict(row.get("input") or {}),
                row.get("origin_channel") or "web",
                row.get("origin_channel_external_id") or "")

    @app.post("/runs/{run_id}/rerun")
    async def rerun(run_id: str, request: Request) -> dict[str, str]:
        """Re-dispara a mesma receita com o mesmo input em uma nova run."""
        recipe, tenant_id, user_id, prev_input, origin_ch, origin_ext = \
            await _load_prev_for_rerun(run_id)
        await _require_user(request, tenant_id=tenant_id)
        new_run = await runner.start(
            recipe=recipe,
            tenant_id=tenant_id,
            user_id=user_id,
            input=prev_input,
            tenant_ctx=await tenant_ctx_provider.snapshot(tenant_id),
            origin_channel=origin_ch,
            origin_channel_external_id=origin_ext,
        )
        return {"run_id": new_run.run_id, "source_run_id": run_id}

    @app.post("/runs/{run_id}/rerun-from/{stage_id}")
    async def rerun_from_stage(run_id: str, stage_id: str, request: Request) -> dict[str, Any]:
        """Re-dispara uma nova run, pulando stages anteriores a `stage_id`
        (copia outputs dos stages anteriores da run original). Útil pra
        repetir só a partir de onde deu ruim."""
        recipe, tenant_id, user_id, prev_input, origin_ch, origin_ext = \
            await _load_prev_for_rerun(run_id)
        await _require_user(request, tenant_id=tenant_id)
        stage_ids = [s.id for s in recipe.stages]
        if stage_id not in stage_ids:
            raise HTTPException(400, f"stage_id '{stage_id}' não existe na receita")
        idx = stage_ids.index(stage_id)
        # carrega outputs dos stages anteriores — memória OU repo
        pre_outputs: dict[str, list] = {}
        try:
            prev = runner.get_run(run_id)
            for sid in stage_ids[:idx]:
                if sid in prev.stages and prev.stages[sid].outputs:
                    pre_outputs[sid] = [dict(o) for o in prev.stages[sid].outputs]
        except KeyError:
            repo = getattr(runner, "_runs_repo", None)
            if repo is not None:
                row = await repo.get(run_id)
                raw = (row or {}).get("stages") or {}
                for sid in stage_ids[:idx]:
                    st = raw.get(sid) or {}
                    outs = st.get("outputs") or []
                    if outs:
                        pre_outputs[sid] = [dict(o) for o in outs]
        new_run = await runner.start(
            recipe=recipe,
            tenant_id=tenant_id,
            user_id=user_id,
            input=prev_input,
            tenant_ctx=await tenant_ctx_provider.snapshot(tenant_id),
            origin_channel=origin_ch,
            origin_channel_external_id=origin_ext,
        )
        # pre-popula os stages anteriores como SUCCESS (copiados da run original)
        from imkt4.recipes.runner import StageStatus as _St
        for sid, outs in pre_outputs.items():
            st = new_run.stages.get(sid)
            if st:
                st.outputs = [dict(o) for o in outs]
                st.status = _St.SUCCESS
        # re-avalia _advance pra disparar o stage alvo (dependências já satisfeitas)
        await runner._advance(new_run)  # type: ignore[attr-defined]
        return {
            "run_id": new_run.run_id,
            "source_run_id": run_id,
            "skipped_stages": list(pre_outputs.keys()),
            "started_from": stage_id,
        }

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        def _ordered_stages(recipe_name: str, raw: dict) -> dict:
            """Reordena dict de stages pela ordem declarada na receita e
            enriquece com `requires` (capability do worker).
            Stages metadata (chaves começando com _) são ignoradas.
            Stages extras (ex.: legado) vão pro fim, após os declarados.
            """
            try:
                recipe = catalog.get(recipe_name)
                order = [s.id for s in recipe.stages]
                caps = {s.id: s.requires for s in recipe.stages}
            except KeyError:
                order, caps = [], {}
            cleaned = {k: v for k, v in raw.items()
                       if not k.startswith("_") and isinstance(v, dict)}
            out: dict[str, Any] = {}
            for sid in order:
                if sid in cleaned:
                    entry = dict(cleaned[sid])
                    if caps.get(sid):
                        entry["requires"] = caps[sid]
                    out[sid] = entry
            for sid, v in cleaned.items():
                if sid not in out:
                    out[sid] = v
            return out

        try:
            run = runner.get_run(run_id)
        except KeyError:
            repo = getattr(runner, "_runs_repo", None)
            if repo is not None:
                row = await repo.get(run_id)
                if row:
                    recipe_name = row.get("recipe_name", "")
                    raw = row.get("stages") or {}
                    # Converte file:// → /artifacts/ nos outputs aninhados
                    for _sid, _stg in (raw or {}).items():
                        if isinstance(_stg, dict) and _stg.get("outputs"):
                            _stg["outputs"] = _urls_in_output(_stg["outputs"])
                    return {
                        "run_id": row["run_id"],
                        "recipe": recipe_name,
                        "tenant_id": row.get("tenant_id"),
                        "user_id": row.get("user_id"),
                        "input": row.get("input") or {},
                        "finished": row.get("finished", False),
                        "failed": row.get("failed", False),
                        "stages": _ordered_stages(recipe_name, raw),
                    }
            raise HTTPException(404, f"run não encontrada: {run_id}")
        _recipe_caps = {s.id: s.requires for s in run.recipe.stages}
        raw_stages = {
            sid: {
                "status": s.status.value,
                "job_ids": list(s.job_ids),
                "error": s.error,
                # Converte file:// → /artifacts/ recursivamente pra UI carregar
                "outputs": _urls_in_output(list(s.outputs)) if s.outputs else s.outputs,
                "requires": _recipe_caps.get(sid),
            }
            for sid, s in run.stages.items()
        }
        return {
            "run_id": run.run_id,
            "recipe": run.recipe.name,
            "tenant_id": run.tenant_id,
            "user_id": run.user_id,
            "input": run.input or {},
            "finished": run.is_finished(),
            "failed": run.has_failed(),
            "stages": _ordered_stages(run.recipe.name, raw_stages),
        }

    @app.delete("/runs/{run_id}")
    async def delete_run(run_id: str, request: Request) -> dict[str, Any]:
        """Remove run permanentemente (memória + Postgres).
        Não remove artefatos no storage (S3/local) — apenas o registro da run.
        """
        # Auth: tenant_id extraído de memória OU DB
        tenant_id = None
        try:
            prev = runner.get_run(run_id)
            tenant_id = prev.tenant_id
        except KeyError:
            repo = getattr(runner, "_runs_repo", None)
            if repo is not None:
                prev_data = await repo.get(run_id)
                if prev_data:
                    tenant_id = prev_data.get("tenant_id")
        if tenant_id is None:
            raise HTTPException(404, f"run {run_id} não encontrada")
        await _require_user(request, tenant_id=tenant_id)

        # Remove da memória se existir
        try:
            runner._runs.pop(run_id, None)
            # Limpa job_index pra qualquer job pendente dessa run
            to_remove = [
                jid for jid, (rid, _sid, _slot) in runner._job_index.items()
                if rid == run_id
            ]
            for jid in to_remove:
                runner._job_index.pop(jid, None)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("imkt4.api").warning(
                "delete run memória falhou: %s", exc,
            )

        # Remove do DB
        deleted = False
        repo = getattr(runner, "_runs_repo", None)
        if repo is not None:
            try:
                deleted = await repo.delete(run_id)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("imkt4.api").warning(
                    "runs_repo.delete falhou: %s", exc,
                )
        return {"deleted": True, "db_deleted": deleted, "run_id": run_id}

    @app.post("/runs/{run_id}/approve")
    async def approve(run_id: str, req: ApprovalRequest, request: Request) -> dict[str, str]:
        try:
            prev = runner.get_run(run_id)
            await _require_user(request, tenant_id=prev.tenant_id)
        except KeyError:
            pass  # 404 já sai em on_approval_decided
        await runner.on_approval_decided(
            run_id, req.stage_id, ApprovalDecision.APPROVED
        )
        return {"status": "ok"}

    @app.post("/runs/{run_id}/reject")
    async def reject(run_id: str, req: ApprovalRequest, request: Request) -> dict[str, str]:
        try:
            prev = runner.get_run(run_id)
            await _require_user(request, tenant_id=prev.tenant_id)
        except KeyError:
            pass
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
    async def publish_run(run_id: str, req: PublishReq, request: Request) -> dict[str, Any]:
        await _require_user(request, tenant_id=req.tenant_id)
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
            records = [_json.loads(ln) for ln in lines if ln]
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

    @app.get("/workers/{name}")
    async def worker_detail(name: str) -> dict[str, Any]:
        """Backlog #21 — detalhe read-only: SKILL.md + recipes que usam +
        capabilities + stats recentes."""
        from pathlib import Path as _Path
        w = None
        for cand in registry.all_workers():
            if cand.name == name:
                w = cand
                break
        if w is None:
            raise HTTPException(404, f"worker desconhecido: {name}")
        status = registry.get_status(w.name)

        # SKILL.md
        skill_md = None
        skill_path = _Path(f"workers/{name}/SKILL.md")
        if skill_path.exists():
            try:
                skill_md = skill_path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                skill_md = None

        # Recipes que chamam alguma das capabilities deste worker
        used_in_recipes = []
        caps = set(w.capabilities)
        try:
            for r in catalog.all():
                stage_uses = []
                for st in r.stages:
                    if st.requires and st.requires in caps:
                        stage_uses.append({
                            "stage_id": st.id, "requires": st.requires,
                            "fanout": bool(st.fanout_over),
                            "needs": list(st.needs),
                        })
                if stage_uses:
                    used_in_recipes.append({
                        "recipe": r.name, "version": r.version,
                        "stages": stage_uses,
                    })
        except Exception:  # noqa: BLE001
            pass

        # Outras capabilities (irmãs neste mesmo worker)
        siblings = []
        for sib in registry.all_workers():
            if sib.name == w.name:
                continue
            common = set(sib.capabilities) & caps
            if common:
                siblings.append({
                    "name": sib.name, "shared_capabilities": sorted(common),
                    "priority": sib.priority,
                    "health": registry.get_status(sib.name).health.value,
                })

        return {
            "name": w.name,
            "capabilities": list(w.capabilities),
            "endpoint": w.endpoint,
            "local": w.local,
            "priority": w.priority,
            "max_concurrent": w.max_concurrent,
            "health": status.health.value,
            "in_flight": status.in_flight,
            "last_error": status.last_error,
            "skill_md": skill_md,
            "used_in_recipes": used_in_recipes,
            "siblings": siblings,
        }

    @app.post("/chat")
    async def chat(req: ChatRequest, request: Request) -> dict[str, Any]:
        await _require_user(request, tenant_id=req.tenant_id)
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

    # ── thumbs dos estilos de text overlay (worker video-text-designer) ─
    # Pré-renderizados pelo script gen_text_style_thumbs.py pra UI mostrar
    # visualmente cada estilo antes do user escolher.
    TEXT_STYLE_THUMBS = Path(
        "./workers/video-text-designer/assets/thumbs"
    ).resolve()

    @app.get("/text-style-thumbs/{slug}.jpg")
    async def get_text_style_thumb(slug: str) -> FileResponse:
        # Só aceita slugs alfanum + underscore (sem path traversal)
        import re
        if not re.fullmatch(r"[a-z0-9_]+", slug):
            raise HTTPException(400, "slug inválido")
        p = (TEXT_STYLE_THUMBS / f"{slug}.jpg").resolve()
        if not str(p).startswith(str(TEXT_STYLE_THUMBS)):
            raise HTTPException(403, "forbidden")
        if not p.exists() or not p.is_file():
            raise HTTPException(404, f"thumb não encontrada: {slug}")
        return FileResponse(p, media_type="image/jpeg")

    # Catálogo dinâmico dos text overlay styles (lido de styles.json)
    @app.get("/text-style-catalog")
    async def text_style_catalog() -> dict[str, Any]:
        import json
        manifest_path = Path(
            "./workers/video-text-designer/styles.json"
        ).resolve()
        if not manifest_path.exists():
            return {"styles": []}
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"erro lendo manifest: {exc}") from exc

    # ── proxy S3/MinIO: streama bytes pelo gateway ────────────────────
    # Soluciona "localhost:9000 quebra em outra máquina" — UI recebe
    # `/s3/<bucket>/<key>` e o gateway busca do MinIO internamente.
    @app.get("/s3/{bucket}/{key:path}")
    async def s3_proxy(bucket: str, key: str):
        import os as _os
        import httpx as _httpx
        from fastapi.responses import StreamingResponse

        endpoint = _os.environ.get("S3_ENDPOINT", "").rstrip("/")
        access_key = _os.environ.get("S3_ACCESS_KEY", "")
        secret_key = _os.environ.get("S3_SECRET_KEY", "")
        if not endpoint:
            raise HTTPException(503, "S3_ENDPOINT não configurado")

        # Gera presigned URL internamente (apontando pro endpoint
        # interno, não exposto ao cliente).
        try:
            import boto3  # noqa: PLC0415
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=_os.environ.get("S3_REGION", "us-east-1"),
            )
            presigned = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=300,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"s3 presign: {exc}") from exc

        # Streama pra o cliente
        async def _stream():
            async with _httpx.AsyncClient(timeout=120.0) as c:
                async with c.stream("GET", presigned) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise HTTPException(
                            resp.status_code,
                            f"upstream: {body[:200].decode(errors='ignore')}",
                        )
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        yield chunk

        # Detecta content-type via mimetypes (simpler que fazer HEAD upstream)
        import mimetypes as _mt
        ctype = _mt.guess_type(key)[0] or "application/octet-stream"
        return StreamingResponse(_stream(), media_type=ctype)

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
        "origin_channel": getattr(r, "origin_channel", "") or "",
        "origin_channel_external_id": getattr(r, "origin_channel_external_id", "") or "",
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _urls_in_output(output: Any) -> Any:
    """Converte recursivamente `file://...data/artifacts/<path>` em
    `/artifacts/<path>` pra UI conseguir carregar no browser.
    Percorre dicts e listas aninhados (ex: outputs[*].text_png_url)."""
    if output is None:
        return output
    if isinstance(output, str):
        if output.startswith("file://"):
            s = output[len("file://"):]
            marker = "/data/artifacts/"
            idx = s.find(marker)
            if idx >= 0:
                return "/artifacts/" + s[idx + len(marker):]
        return output
    if isinstance(output, list):
        return [_urls_in_output(x) for x in output]
    if isinstance(output, dict):
        return {k: _urls_in_output(v) for k, v in output.items()}
    return output
