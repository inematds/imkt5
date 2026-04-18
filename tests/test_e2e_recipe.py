"""End-to-end: receita roda inteira no InMemoryDispatcher.

Testa que:
- stages respeitam `needs`
- `parallel` dispara N jobs
- `fanout_over` dispara um por item
- `when` pula estágios
- aprovação `auto_reviewer` bloqueia/libera via callback
- Recipe run termina com todos stages terminal
"""

import asyncio
from typing import Any

import pytest

from imkt4.gateway import InMemoryDispatcher
from imkt4.recipes import RecipeRunner, load_recipe
from imkt4.recipes.approvals import CompositeApprovalGate
from imkt4.types.approvals import ApprovalDecision


# ── mock auto_reviewer: sempre aprova ─────────────────────────────
class AlwaysApproveAuto:
    async def evaluate(self, *, tenant_id, run_id, stage_id, artifacts, criteria):
        return ApprovalDecision.APPROVED


# ── mock user gate: auto-aprova via callback após 1ms ─────────────
class AutoUserGate:
    def __init__(self, runner):
        self._runner = runner

    async def ask(
        self, *, tenant_id, user_id, origin_channel, origin_external_id,
        run_id, stage_id, question,
    ):
        # simula usuário respondendo "sim" imediatamente
        await asyncio.sleep(0)
        await self._runner.on_approval_decided(
            run_id, stage_id, ApprovalDecision.APPROVED
        )


class AutoReviewerGate:
    def __init__(self, runner):
        self._runner = runner

    async def ask(self, *, tenant_id, reviewer_role, run_id, stage_id, question):
        await asyncio.sleep(0)
        await self._runner.on_approval_decided(
            run_id, stage_id, ApprovalDecision.APPROVED
        )


# ── handlers mock (um por capability usada na receita) ───────────
async def _make_handlers(payloads_seen: dict[str, list[dict]]):
    def make(name: str, output: dict[str, Any]):
        async def h(job):
            payloads_seen.setdefault(name, []).append(job.payload)
            return output
        return h
    return {
        "research.market": make("research", {"insights": ["x", "y"]}),
        "brief.strategic": make("brief", {
            "creative_brief": {"campaign_angle": "test", "approved_ctas": ["Compre"]}
        }),
        "copy.platform": make("copy", {
            "copy": {
                "key_benefit": "benefício chave",
                "threads_post": "curto",
                "instagram_caption": "legenda",
                "youtube": {"title": "t", "description": "d", "tags": ["x"]},
            }
        }),
        "design.ad_layout": make("ad_design", {
            "ad_design": {
                "variants": [
                    {"background_prompt": f"p{i}", "negative_prompt": "n"}
                    for i in range(3)
                ]
            }
        }),
        "image.generation": make("images", {"image_url": "img.png"}),
        "audio.tts": make("voiceover", {"audio_url": "a.mp3"}),
        "video.cinematic": make("video", {"scene_plan": {"scenes": []}}),
        "video.render": make("video_render", {"video_url": "v.mp4", "duration_s": 15.0}),
        "platform.instagram": make("ig", {"post": "ig"}),
        "platform.youtube": make("yt", {"post": "yt"}),
        "platform.tiktok": make("tt", {"post": "tt"}),
        "platform.facebook": make("fb", {"post": "fb"}),
        "platform.threads": make("th", {"post": "th"}),
        "platform.linkedin": make("li", {"post": "li"}),
        "video.source_ingest": make("ingest", {"new_lives": ["L1"]}),
        "video.clip_extraction": make("clip", {"clip_path": "c.mp4"}),
        "video.publish": make("publish", {"url": "yt.com/abc"}),
    }


async def _run_recipe_to_completion(recipe_path: str, *, input, tenant_ctx):
    payloads_seen: dict[str, list[dict]] = {}
    dispatcher = InMemoryDispatcher()
    gate = CompositeApprovalGate(
        on_decided=lambda *a, **kw: asyncio.sleep(0),  # substituído depois
        auto_gate=AlwaysApproveAuto(),
    )
    runner = RecipeRunner(dispatcher=dispatcher, approval_gate=gate)
    # agora que runner existe, reconecta callbacks com runner concreto
    gate._on_decided = runner.on_approval_decided
    gate._user_gate = AutoUserGate(runner)
    gate._reviewer_gate = AutoReviewerGate(runner)

    # registra handlers
    handlers = await _make_handlers(payloads_seen)
    for cap, h in handlers.items():
        dispatcher.register_capability(cap, h)

    # callback de fim de job → runner
    dispatcher.set_on_finish(
        lambda job_id, success, output, error:
        runner.on_job_finished(job_id, success=success, output=output, error=error)
    )

    await dispatcher.start()

    run = await runner.start(
        recipe=load_recipe(recipe_path),
        tenant_id="t1",
        user_id="u1",
        input=input,
        tenant_ctx=tenant_ctx,
        origin_channel="test",
        origin_channel_external_id="test-chat",
    )

    # aguarda todos os stages terminarem (com timeout de segurança)
    for _ in range(500):  # máx 5s (500 * 10ms)
        if run.is_finished():
            break
        await asyncio.sleep(0.01)

    await dispatcher.stop()
    return run, payloads_seen


async def test_campanha_roda_completa():
    run, payloads = await _run_recipe_to_completion(
        "recipes/campanha-marketing.yaml",
        input={"brief": "lançamento X", "with_research": True},
        tenant_ctx={
            "profile": {"visual_style": "minimalist", "voice_id": "v1"},
        },
    )

    assert run.is_finished(), {
        sid: s.status.value for sid, s in run.stages.items()
    }
    assert not run.has_failed()

    # images é fanout_over das 3 variants do ad_design → 3 chamadas
    assert len(payloads["images"]) == 3

    # stage platforms foi comentado (workers platform-* diferidos)
    # — validar que a receita foi até video com sucesso
    assert "video" in run.stages
    assert run.stages["video"].status.value == "success"


async def test_dep_failure_cascades_through_skip():
    """Se brief falha, descendentes (copy, ad_design, images, video) devem
    ser SKIPPED com error='dep_failed' — NÃO devem tentar rodar com
    payload vazio."""
    dispatcher = InMemoryDispatcher()
    runner = RecipeRunner(
        dispatcher=dispatcher,
        approval_gate=CompositeApprovalGate(
            on_decided=runner.on_approval_decided if False else (lambda *a: None),  # stub
            auto_gate=AlwaysApproveAuto(),
        ),
    )

    # Tem que reconfigurar o callback do approval_gate apontando pro runner
    gate = CompositeApprovalGate(
        on_decided=runner.on_approval_decided,
        auto_gate=AlwaysApproveAuto(),
    )
    runner._approvals = gate

    payloads_seen: dict[str, list[dict]] = {}

    def make_ok(name, out):
        async def h(job):
            payloads_seen.setdefault(name, []).append(job.payload)
            return out
        return h

    async def failing(job):
        payloads_seen.setdefault("brief", []).append(job.payload)
        raise RuntimeError("brief explodiu")

    dispatcher.register_capability("research.market", make_ok("research", {}))
    dispatcher.register_capability("brief.strategic", failing)
    # Os abaixo NÃO devem ser chamados por causa do cascade:
    dispatcher.register_capability("copy.platform", make_ok("copy", {"copy": {"key_benefit": "x"}}))
    dispatcher.register_capability("design.ad_layout", make_ok("ad_design", {"ad_design": {"variants": []}}))
    dispatcher.register_capability("image.generation", make_ok("images", {"image_url": "i"}))
    dispatcher.register_capability("audio.tts", make_ok("voiceover", {"audio_url": "a"}))
    dispatcher.register_capability("video.cinematic", make_ok("video", {"scene_plan": {}}))
    dispatcher.register_capability("video.render", make_ok("video_render", {"video_url": "v.mp4"}))

    dispatcher.set_on_finish(
        lambda job_id, success, output, error:
        runner.on_job_finished(job_id, success=success, output=output, error=error)
    )

    await dispatcher.start()
    run = await runner.start(
        recipe=load_recipe("recipes/campanha-marketing.yaml"),
        tenant_id="t1", user_id="u1",
        input={"brief": "x", "with_research": False},
        tenant_ctx={"profile": {}},
        origin_channel="test", origin_channel_external_id="t",
    )
    for _ in range(500):
        if run.is_finished(): break
        await asyncio.sleep(0.01)
    await dispatcher.stop()

    assert run.is_finished(), {sid: s.status.value for sid, s in run.stages.items()}
    assert run.stages["brief"].status.value == "failed"
    # descendentes devem estar SKIPPED (por dep_failed) — sem payload chamado
    for sid in ("copy", "ad_design", "images", "voiceover", "video", "video_render"):
        assert run.stages[sid].status.value == "skipped", sid
        assert run.stages[sid].error == "dep_failed", sid
    # nenhum worker descendente deve ter sido chamado
    for name in ("copy", "ad_design", "images", "voiceover", "video", "video_render"):
        assert name not in payloads_seen, f"{name} rodou mesmo com brief failed"


async def test_research_opt_out():
    """Se with_research=false, stage research é SKIPPED."""
    run, _ = await _run_recipe_to_completion(
        "recipes/campanha-marketing.yaml",
        input={"brief": "lançamento X", "with_research": False},
        tenant_ctx={"profile": {"visual_style": "minimalist", "voice_id": "v1"}},
    )
    assert run.is_finished()
    assert run.stages["research"].status.value == "skipped"
    # brief deve ter rodado mesmo sem research
    assert run.stages["brief"].status.value == "success"


async def test_yt_clip_publish_fanout():
    run, payloads = await _run_recipe_to_completion(
        "recipes/yt-clip-publish.yaml",
        input={},
        tenant_ctx={
            "profile": {"prompts": {"cortes": "prompt corte"}},
            "source_bindings": [
                {"binding_id": "s1", "external_id": "CH_SRC_1"},
                {"binding_id": "s2", "external_id": "CH_SRC_2"},
            ],
            "publish_bindings": [
                {"binding_id": "d1", "external_id": "CH_DST_1"},
                {"binding_id": "d2", "external_id": "CH_DST_2"},
                {"binding_id": "d3", "external_id": "CH_DST_3"},
            ],
        },
    )
    assert run.is_finished(), {
        sid: s.status.value for sid, s in run.stages.items()
    }
    assert not run.has_failed()

    # ingest: fanout_over 2 sources
    assert len(payloads["ingest"]) == 2
    # publish: fanout_over 3 destinos
    assert len(payloads["publish"]) == 3


async def test_simple_carrossel():
    run, payloads = await _run_recipe_to_completion(
        "recipes/carrossel-simples.yaml",
        input={
            "prompt": "minimalist coffee shop",
            "model": "flux2-klein",
            "title": "Meu Carrossel",
        },
        tenant_ctx={},
    )
    assert run.is_finished()
    assert not run.has_failed()
    # images parallel: 2 (default realista pra 1 GPU)
    assert len(payloads["images"]) == 2


# design.carousel handler → retorna carrossel pronto
@pytest.fixture(autouse=True)
def _add_carousel_handler(monkeypatch):
    # garante que handlers cobrem design.carousel
    original = _make_handlers

    async def wrapped(payloads_seen):
        h = await original(payloads_seen)

        async def carousel(job):
            payloads_seen.setdefault("carrossel", []).append(job.payload)
            return {"carrossel_url": "c.pdf"}

        h["design.carousel"] = carousel
        h["design.carousel_rich"] = carousel   # carrossel-simples usa rich agora
        return h

    monkeypatch.setattr("tests.test_e2e_recipe._make_handlers", wrapped)
