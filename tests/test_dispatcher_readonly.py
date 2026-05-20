"""Test dispatcher read-only flow."""

import pytest
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.session import SessionStore
from gateway.security.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_dispatch_unauthorized(tmp_path):
    store = SessionStore(str(tmp_path / "test.sqlite"))
    await store.open()
    auth = AuthProvider(allowed_users=[1])
    disp = Dispatcher(auth, store)

    # Mock update with user 999 (not allowed)
    class _Msg:
        async def reply_text(self, text):
            assert "Unauthorized" in text

    class _Chat:
        id = 999

    class _User:
        id = 999

    class _Upd:
        effective_user = _User()
        effective_chat = _Chat()
        message = _Msg()

    was = []

    async def handler(upd, ctx):
        was.append(1)

    await disp.dispatch(_Upd(), None, "test", handler)
    assert len(was) == 0  # handler NOT called
    await store.close()


@pytest.mark.asyncio
async def test_dispatch_authorized(tmp_path):
    store = SessionStore(str(tmp_path / "test2.sqlite"))
    await store.open()
    auth = AuthProvider(allowed_users=[1])
    disp = Dispatcher(auth, store)

    called = []

    class _Msg:
        async def reply_text(self, text):
            pass

    class _Chat:
        id = 100

    class _User:
        id = 1

    class _Upd:
        effective_user = _User()
        effective_chat = _Chat()
        message = _Msg()

    async def handler(upd, ctx):
        called.append(1)

    await disp.dispatch(_Upd(), None, "test", handler)
    assert len(called) == 1
    await store.close()
