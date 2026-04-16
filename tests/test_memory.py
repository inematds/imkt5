"""Memory store multi-tenant."""

import tempfile
from pathlib import Path

import pytest

from imkt4.memory import MemoryCategory, MemoryStore


@pytest.fixture
async def store():
    with tempfile.TemporaryDirectory() as d:
        s = MemoryStore(Path(d) / "mem.db")
        await s.init()
        yield s


async def test_save_and_recent(store):
    await store.save(
        tenant_id="t1",
        user_id="u1",
        content="a usuária gosta de cor azul",
        category=MemoryCategory.PREFERENCE,
    )
    r = await store.recent(tenant_id="t1", user_id="u1")
    assert len(r) == 1
    assert r[0].content == "a usuária gosta de cor azul"
    assert r[0].category == MemoryCategory.PREFERENCE


async def test_tenant_isolation(store):
    await store.save(
        tenant_id="t1",
        user_id="u1",
        content="fato do tenant 1",
        category=MemoryCategory.FACT,
    )
    await store.save(
        tenant_id="t2",
        user_id="u1",
        content="fato do tenant 2",
        category=MemoryCategory.FACT,
    )
    r1 = await store.recent(tenant_id="t1", user_id="u1")
    r2 = await store.recent(tenant_id="t2", user_id="u1")
    assert len(r1) == 1 and len(r2) == 1
    assert r1[0].content == "fato do tenant 1"
    assert r2[0].content == "fato do tenant 2"


async def test_search_fts(store):
    await store.save(
        tenant_id="t1",
        user_id="u1",
        content="reunião com cliente X sobre proposta",
        category=MemoryCategory.CONVERSATION,
    )
    await store.save(
        tenant_id="t1",
        user_id="u1",
        content="preferência: resposta sempre em português",
        category=MemoryCategory.PREFERENCE,
    )
    results = await store.search(
        tenant_id="t1", user_id="u1", query="cliente"
    )
    assert len(results) == 1
    assert "cliente X" in results[0].content


async def test_search_scoped_by_user(store):
    await store.save(
        tenant_id="t1", user_id="u1", content="algo do u1",
        category=MemoryCategory.FACT,
    )
    await store.save(
        tenant_id="t1", user_id="u2", content="algo do u2",
        category=MemoryCategory.FACT,
    )
    r = await store.search(tenant_id="t1", user_id="u1", query="algo")
    assert len(r) == 1
    assert r[0].user_id == "u1"


async def test_forget(store):
    mid = await store.save(
        tenant_id="t1", user_id="u1", content="vai ser esquecido",
        category=MemoryCategory.FACT,
    )
    assert await store.forget(tenant_id="t1", user_id="u1", memory_id=mid)
    assert len(await store.recent(tenant_id="t1", user_id="u1")) == 0


async def test_forget_wrong_tenant(store):
    mid = await store.save(
        tenant_id="t1", user_id="u1", content="a",
        category=MemoryCategory.FACT,
    )
    # tentar esquecer com tenant errado não deve deletar
    assert not await store.forget(tenant_id="t2", user_id="u1", memory_id=mid)
    assert len(await store.recent(tenant_id="t1", user_id="u1")) == 1
