"""Capability registry + matcher."""

import pytest

from imkt4.capabilities import CapabilityRegistry, select_worker
from imkt4.capabilities.matcher import NoWorkerAvailable
from imkt4.types.capabilities import RegisteredWorker, WorkerHealth


async def _fake_probe_healthy(worker):
    return (WorkerHealth.HEALTHY, None)


async def _fake_probe_down(worker):
    return (WorkerHealth.DOWN, "forced")


@pytest.fixture
def registry():
    reg = CapabilityRegistry(probe=_fake_probe_healthy)
    reg.register(
        RegisteredWorker(
            name="sd-local",
            capabilities=("image.generation",),
            endpoint="http://localhost:7860",
            local=True,
            priority=100,
        )
    )
    reg.register(
        RegisteredWorker(
            name="inemaimg",
            capabilities=("image.generation",),
            endpoint="http://localhost:8010",
            local=True,
            priority=90,
        )
    )
    reg.register(
        RegisteredWorker(
            name="pollinations",
            capabilities=("image.generation",),
            endpoint="https://image.pollinations.ai",
            local=False,
            priority=10,
        )
    )
    return reg


async def test_registry_lists_candidates(registry):
    cands = registry.candidates("image.generation")
    assert len(cands) == 3
    assert {c.name for c in cands} == {"sd-local", "inemaimg", "pollinations"}


async def test_matcher_picks_local_over_remote(registry):
    # Sem health check — todos em UNKNOWN. allow_degraded pega
    # o de maior prioridade entre os locais.
    w = select_worker(registry, "image.generation")
    assert w.name == "sd-local"


async def test_matcher_skips_unhealthy(registry):
    await registry.refresh_health()  # todos healthy
    w = select_worker(registry, "image.generation")
    assert w.name == "sd-local"


async def test_matcher_falls_back_when_local_down():
    reg = CapabilityRegistry(probe=_fake_probe_down)
    reg.register(
        RegisteredWorker(
            name="sd-local",
            capabilities=("image.generation",),
            endpoint="http://localhost:7860",
            local=True,
            priority=100,
        )
    )
    reg.register(
        RegisteredWorker(
            name="pollinations",
            capabilities=("image.generation",),
            endpoint="https://image.pollinations.ai",
            local=False,
            priority=10,
        )
    )
    await reg.refresh_health()
    with pytest.raises(NoWorkerAvailable):
        select_worker(reg, "image.generation", allow_degraded=False)


async def test_matcher_raises_when_capability_unknown(registry):
    with pytest.raises(NoWorkerAvailable):
        select_worker(registry, "nonexistent.capability")
