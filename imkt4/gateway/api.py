"""Gateway HTTP (FastAPI).

Endpoints mínimos:

- POST  /jobs                    — quick dispatch
- GET   /jobs/{job_id}          — status
- POST  /recipes/{name}/run     — executa receita
- GET   /runs/{run_id}          — status de uma run
- POST  /runs/{run_id}/approve  — aprovar um stage (user ou reviewer)
- POST  /runs/{run_id}/reject   — rejeitar
- GET   /workers                — listar workers registrados + health
- GET   /capabilities           — capabilities oferecidas e por quem

Este módulo é intencionalmente thin — compõe os objetos já construídos
(`CapabilityRegistry`, `RecipeRunner`, `InMemoryDispatcher` / `JobQueue`).
A construção vem do `main.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.recipes.runner import RecipeRunner
from imkt4.tools.run_recipe import StaticRecipeCatalog
from imkt4.types.approvals import ApprovalDecision
from imkt4.types.jobs import Job, JobPriority


# ── schemas de requisição ────────────────────────────────────────────
class DispatchRequest(BaseModel):
    tenant_id: str
    user_id: str
    capability: str | None = None
    worker_type: str | None = None
    payload: dict[str, Any] = {}
    priority: str = "normal"
    origin_channel: str = "http"
    origin_channel_external_id: str = ""


class RunRecipeRequest(BaseModel):
    tenant_id: str
    user_id: str
    input: dict[str, Any] = {}
    origin_channel: str = "http"
    origin_channel_external_id: str = ""


class ApprovalRequest(BaseModel):
    stage_id: str
    reason: str = ""


# ── app factory ──────────────────────────────────────────────────────
def create_app(
    *,
    registry: CapabilityRegistry,
    runner: RecipeRunner,
    catalog: StaticRecipeCatalog,
    dispatcher: Any,  # InMemoryDispatcher ou algo que satisfaça JobDispatcher
    tenant_ctx_provider: Any,
) -> FastAPI:
    app = FastAPI(title="imkt4 Gateway", version="0.0.1")

    priority_map = {
        "low": JobPriority.LOW,
        "normal": JobPriority.NORMAL,
        "high": JobPriority.HIGH,
    }

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
        await dispatcher.dispatch(job)
        return {"job_id": job.job_id}

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
                    "health": s.health.value,
                    "in_flight": s.in_flight,
                    "last_error": s.last_error,
                }
            )
        return out

    @app.get("/capabilities")
    async def list_capabilities() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for w in registry.all_workers():
            for cap in w.capabilities:
                out.setdefault(cap, []).append(w.name)
        return out

    return app
