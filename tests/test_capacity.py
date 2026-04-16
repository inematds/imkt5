"""Saturação por max_concurrent + load-balancing entre instâncias."""

import asyncio
import pytest

from imkt4.capabilities import CapabilityRegistry, select_worker
from imkt4.capabilities.matcher import NoWorkerAvailable
from imkt4.types.capabilities import RegisteredWorker, WorkerHealth


async def _healthy(_):
    return (WorkerHealth.HEALTHY, None)


async def _make_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry(probe=_healthy)
    # duas "GPUs" rodando inemaimg, cada uma serializa (max=1)
    reg.register(RegisteredWorker(
        name="inemaimg-gpu0",
        capabilities=("image.generation",),
        endpoint="http://localhost:8010",
        local=True, priority=100, max_concurrent=1,
    ))
    reg.register(RegisteredWorker(
        name="inemaimg-gpu1",
        capabilities=("image.generation",),
        endpoint="http://localhost:8011",
        local=True, priority=100, max_concurrent=1,
    ))
    # remoto fallback
    reg.register(RegisteredWorker(
        name="pollinations",
        capabilities=("image.generation",),
        endpoint="https://image.pollinations.ai",
        local=False, priority=10, max_concurrent=10,
    ))
    await reg.refresh_health()
    return reg


async def test_load_balance_distribui_entre_instancias():
    """1º job vai pra gpu0; 2º (com gpu0 ocupada) vai pra gpu1."""
    reg = await _make_registry()

    w1 = select_worker(reg, "image.generation")
    await reg.acquire(w1.name)
    w2 = select_worker(reg, "image.generation")

    assert {w1.name, w2.name} == {"inemaimg-gpu0", "inemaimg-gpu1"}


async def test_saturacao_force_fallback_pro_remoto():
    """Quando 2 GPUs locais saturadas, escolhe pollinations (remoto)."""
    reg = await _make_registry()
    await reg.acquire("inemaimg-gpu0")
    await reg.acquire("inemaimg-gpu1")

    w = select_worker(reg, "image.generation")
    assert w.name == "pollinations"


async def test_saturacao_total_levanta_excecao():
    reg = CapabilityRegistry(probe=_healthy)
    reg.register(RegisteredWorker(
        name="solo",
        capabilities=("image.generation",),
        endpoint="http://localhost:8010",
        local=True, max_concurrent=1,
    ))
    await reg.refresh_health()
    await reg.acquire("solo")

    with pytest.raises(NoWorkerAvailable) as exc:
        select_worker(reg, "image.generation")
    assert "in_flight" in str(exc.value)


async def test_release_libera_slot():
    reg = await _make_registry()
    await reg.acquire("inemaimg-gpu0")
    await reg.acquire("inemaimg-gpu1")
    await reg.release("inemaimg-gpu0")

    w = select_worker(reg, "image.generation")
    assert w.name == "inemaimg-gpu0"


async def test_respect_capacity_false_aceita_overload():
    """Modo escape: ignorar saturação (cliente assume risco de fila)."""
    reg = await _make_registry()
    await reg.acquire("inemaimg-gpu0")
    await reg.acquire("inemaimg-gpu1")

    w = select_worker(reg, "image.generation", respect_capacity=False)
    # ainda prefere local (gpu0 ou gpu1) sobre remoto
    assert w.name in ("inemaimg-gpu0", "inemaimg-gpu1")
