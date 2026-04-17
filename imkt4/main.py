"""imkt4 main — bootstrap completo do Gateway.

Carrega config, registry, recipes; monta dispatcher + runner + FastAPI;
sobe uvicorn.

Uso:

    python -m imkt4.main
    # ou
    .venv/bin/python -m imkt4.main

Variáveis de ambiente principais (lidas do .env automaticamente se
python-dotenv estiver disponível):

    GATEWAY_HOST=0.0.0.0
    GATEWAY_PORT=8080
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn

from imkt4.capabilities.registry import CapabilityRegistry
from imkt4.gateway.api import create_app
from imkt4.gateway.http_dispatcher import HttpDispatcher
from imkt4.gateway.jobs_store import JobsStore
from imkt4.recipes.approvals import CompositeApprovalGate
from imkt4.recipes.loader import load_recipes_from_dir
from imkt4.recipes.runner import RecipeRunner
from imkt4.tools.run_recipe import StaticRecipeCatalog
from imkt4.types.approvals import ApprovalDecision


# ── carrega .env manualmente (sem dependência) ────────────────────────
def _load_env(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ── tenant context provider — stub (Postgres real depois) ─────────────
class StubTenantContext:
    """Provedor de contexto do tenant. Stub — em prod, lê de Postgres."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {
            "demo": {
                "tenant_id": "demo",
                "name": "Demo Tenant",
                "profile": {
                    "visual_style": "minimalist",
                    "voice_id": "default",
                    "prompts": {
                        "cortes": "Identifique tópicos coesos de 30-180s",
                    },
                },
                "source_bindings": [],
                "publish_bindings": [],
            },
        }

    async def snapshot(self, tenant_id: str) -> dict[str, Any]:
        return self._data.get(tenant_id, {"tenant_id": tenant_id})

    def upsert(self, tenant_id: str, data: dict[str, Any]) -> None:
        self._data[tenant_id] = data


class _AutoReviewGate:
    """Despacha review pra worker auto-reviewer real (via dispatcher)."""

    def __init__(self, dispatcher: HttpDispatcher, registry: CapabilityRegistry) -> None:
        self._dispatcher = dispatcher
        self._registry = registry
        self._results: dict[str, asyncio.Future] = {}

    async def evaluate(
        self, *, tenant_id, run_id, stage_id, artifacts, criteria,
    ) -> ApprovalDecision:
        # Usa o auto-reviewer worker registrado.
        from imkt4.types.jobs import Job
        import uuid
        from imkt4.capabilities.matcher import select_worker

        job = Job(
            job_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id="auto",
            required_capability="review.auto",
            payload={"criteria": list(criteria), "artifacts": artifacts},
            origin_channel="recipe",
            origin_channel_external_id=run_id,
        )

        # Chama o worker direto via http (sync esperando)
        worker = select_worker(self._registry, "review.auto")
        await self._registry.acquire(worker.name)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(
                    f"{worker.endpoint.rstrip('/')}/execute",
                    json={
                        "job_id": job.job_id,
                        "tenant_id": tenant_id,
                        "user_id": "auto",
                        "required_capability": "review.auto",
                        "payload": job.payload,
                    },
                )
                r.raise_for_status()
                output = r.json().get("output", {})
        finally:
            await self._registry.release(worker.name)

        decision_str = output.get("decision", "uncertain")
        try:
            return ApprovalDecision(decision_str)
        except ValueError:
            return ApprovalDecision.UNCERTAIN


# ── main ──────────────────────────────────────────────────────────────
def main() -> None:
    _load_env()

    workers_yaml = os.environ.get("IMKT4_WORKERS_YAML", "config/workers.yaml")
    recipes_dir = os.environ.get("IMKT4_RECIPES_DIR", "recipes")

    if not Path(workers_yaml).exists():
        print(f"erro: {workers_yaml} não encontrado", file=sys.stderr)
        sys.exit(1)

    registry = CapabilityRegistry.from_yaml(workers_yaml)
    recipes = load_recipes_from_dir(recipes_dir) if Path(recipes_dir).exists() else {}
    catalog = StaticRecipeCatalog(recipes)

    # Jobs store: Postgres se POSTGRES_URL configurado, in-memory senão.
    # IMPORTANTE: conectar o pool SÓ no startup event (mesmo event loop do uvicorn).
    from imkt4.db.pool import get_pool
    db = get_pool()
    jobs_store: Any
    if db is not None:
        from imkt4.db.jobs_repo import PostgresJobsStore
        jobs_store = PostgresJobsStore(db)
        print("[boot] usando Postgres jobs store (connect no startup)")
    else:
        jobs_store = JobsStore()
        print("[boot] usando JobsStore in-memory (POSTGRES_URL não setado)")
    dispatcher = HttpDispatcher(registry=registry, jobs_store=jobs_store)

    # Approval gate composto — montado depois que runner existe (callback ref)
    runner_ref = {"runner": None}

    async def _on_decided(run_id, stage_id, decision):
        if runner_ref["runner"]:
            await runner_ref["runner"].on_approval_decided(
                run_id, stage_id, decision
            )

    tenant_ctx = StubTenantContext()

    auto_gate = _AutoReviewGate(dispatcher, registry)
    approval_gate = CompositeApprovalGate(
        on_decided=_on_decided,
        auto_gate=auto_gate,
    )
    runner = RecipeRunner(dispatcher=dispatcher, approval_gate=approval_gate)
    runner_ref["runner"] = runner

    # Gates reais: user_gate pergunta no canal; human_reviewer idem pro reviewer.
    from imkt4.channels.base import ChannelRegistry
    from imkt4.recipes.approvals.telegram_gates import UserApprovalGate, HumanReviewerGate
    channels_registry = ChannelRegistry()
    user_gate = UserApprovalGate(channels=channels_registry, on_decided=_on_decided)
    human_reviewer_gate = HumanReviewerGate(
        user_gate=user_gate,
        tenant_ctx_provider=tenant_ctx,
    )
    approval_gate._user_gate = user_gate
    approval_gate._reviewer_gate = human_reviewer_gate

    # ligação dispatcher → runner (callback de fim de job)
    dispatcher.set_on_finish(
        lambda jid, ok, out, err:
        runner.on_job_finished(jid, success=ok, output=out, error=err)
    )

    # ── Agent loop: LLM + tools (quick-dispatch + run-recipe) ─────────
    from imkt4.agent import AgentLoop, ContextBuilder
    from imkt4.agent.loop import AgentConfig
    from imkt4.memory.store import MemoryStore
    from imkt4.providers.ollama import OllamaProvider
    from imkt4.providers.openrouter import OpenRouterProvider
    from imkt4.tools.base import BaseTool
    from imkt4.tools.dispatch_job import DispatchJobTool
    from imkt4.tools.registry import ToolRegistry
    from imkt4.tools.run_recipe import RunRecipeTool
    from imkt4.config import load as _load_cfg

    memory = MemoryStore(_load_cfg().memory.db_path)

    provider_name = os.environ.get("IMKT4_AGENT_PROVIDER", "ollama")
    if provider_name == "openrouter":
        provider = OpenRouterProvider()
        agent_model = os.environ.get("IMKT4_AGENT_MODEL", _load_cfg().llm.openrouter.default_model)
    else:
        provider = OllamaProvider()
        agent_model = os.environ.get("IMKT4_AGENT_MODEL", _load_cfg().llm.ollama.router_model)

    tool_registry = ToolRegistry()
    tool_registry.register(DispatchJobTool(submitter=dispatcher))
    tool_registry.register(RunRecipeTool(catalog=catalog, runner=runner, tenant_ctx_provider=tenant_ctx))

    agent = AgentLoop(
        provider=provider,
        tools=tool_registry,
        context_builder=ContextBuilder(memory=memory),
        memory=memory,
        config=AgentConfig(model=agent_model, temperature=0.3),
    )

    app = create_app(
        registry=registry,
        runner=runner,
        catalog=catalog,
        dispatcher=dispatcher,
        tenant_ctx_provider=tenant_ctx,
        jobs_store=jobs_store,
        agent=agent,
        memory=memory,
    )

    # boot: starta dispatcher + health refresh inicial
    # ── Canal Telegram (se config presente) ──────────────────────────
    from imkt4.channels.telegram import TelegramChannel, TelegramIdentity
    tg_channel: TelegramChannel | None = None
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    tg_allowed = {
        int(x) for x in tg_allowed_raw.split(",") if x.strip().lstrip("-").isdigit()
    }
    if tg_token and tg_allowed:
        # Hoje: todo chat_id autorizado vai pro tenant 'inema'.
        # Depois (DB), ler de channel_bindings.
        identity_map = {
            cid: TelegramIdentity(tenant_id="inema", user_id=f"tg-{cid}")
            for cid in tg_allowed
        }
        tenancy_repo = None
        if db is not None:
            from imkt4.db.tenancy_repo import TenancyRepo
            tenancy_repo = TenancyRepo(db)
        tg_channel = TelegramChannel(
            bot_token=tg_token,
            allowed_chat_ids=tg_allowed,
            identity_map=identity_map,
            default_tenant_id="inema",
            on_approval=user_gate.resolve,
            tenancy_repo=tenancy_repo,
        )
        channels_registry.register(tg_channel)

    async def _on_message_from_channel(inc):
        return await agent.process_message(inc)

    @app.on_event("startup")
    async def _startup() -> None:
        # Conecta Postgres no MESMO event loop do uvicorn
        if db is not None:
            try:
                await db.connect()
                print("[boot] Postgres pool conectado")
            except Exception as exc:
                print(f"[boot] Postgres connect falhou: {exc} — usando in-memory")
                nonlocal_store = JobsStore()
                dispatcher._jobs_store = nonlocal_store

        await memory.init()
        await dispatcher.start()
        try:
            await asyncio.wait_for(registry.refresh_health(), timeout=10.0)
        except asyncio.TimeoutError:
            print("[boot] health-check inicial timeout; seguindo")

        if tg_channel is not None:
            try:
                await tg_channel.start(_on_message_from_channel)
                print(f"[boot] Telegram channel conectado (chats autorizados: {sorted(tg_allowed)})")
            except Exception as exc:  # noqa: BLE001
                print(f"[boot] Telegram channel falhou: {exc}")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if tg_channel is not None:
            try:
                await tg_channel.stop()
            except Exception:  # noqa: BLE001
                pass
        await dispatcher.stop()
        if db is not None:
            try:
                await db.close()
            except Exception:  # noqa: BLE001
                pass

    host = os.environ.get("GATEWAY_HOST", "0.0.0.0")
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    print(f"\n  imkt4 gateway → http://{host}:{port}")
    print(f"  workers:   {len(registry.all_workers())}  ({workers_yaml})")
    print(f"  recipes:   {len(recipes)}  ({recipes_dir})\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
