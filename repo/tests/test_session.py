"""Test session store with aiosqlite."""

import pytest
from gateway.core.session import SessionStore, TelegramSession


@pytest.mark.asyncio
async def test_store(tmp_path):
    db = str(tmp_path / "test.sqlite")
    store = SessionStore(db)
    await store.open()

    # upsert & get
    s = TelegramSession(chat_id=1, user_id=100, role="readonly")
    await store.upsert_session(s)
    got = await store.get_session(1, 100)
    assert got is not None
    assert got.chat_id == 1
    assert got.user_id == 100
    assert got.role == "readonly"

    # bind
    await store.bind_flow(1, 100, "flow_abc")
    got = await store.get_session(1, 100)
    assert got.active_flow_id == "flow_abc"

    # audit
    aid = await store.audit(100, 1, "test", risk="low", allowed=True)
    assert aid > 0

    await store.close()


@pytest.mark.asyncio
async def test_store_no_session(tmp_path):
    store = SessionStore(str(tmp_path / "empty.sqlite"))
    await store.open()
    got = await store.get_session(999, 999)
    assert got is None
    await store.close()
