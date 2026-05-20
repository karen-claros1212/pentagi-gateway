from __future__ import annotations

import time

import pytest

from gateway.config import Settings
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.session import SessionStore
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


async def make_dispatcher(tmp_path, mode="READ_ONLY", delete_enabled=False, admins=None, ttl=300):
    store = SessionStore(str(tmp_path / "gateway.sqlite"))
    await store.open()
    auth = AuthProvider(allowed_users=[1, 2], admins=admins or [])
    client = MockPentagiClient()
    settings = Settings(
        gateway_mode=mode,
        delete_flow_enabled=delete_enabled,
        approval_ttl_seconds=ttl,
    )
    dispatcher = Dispatcher(auth, store, settings=settings, client=client)
    return dispatcher, store, client


@pytest.mark.asyncio
async def test_read_only_blocks_create_flow_and_input(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path)
    update = FakeUpdate(text="crea un flow para revisar")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "READ_ONLY" in update.message.replies[-1]
    await store.bind_flow(10, 1, "1234")
    update2 = FakeUpdate(text="dile que continúe")
    await dispatcher.handle_text(update2, FakeContext(), update2.message.text)
    assert "READ_ONLY" in update2.message.replies[-1]
    assert client.mutations == []
    await store.close()


@pytest.mark.asyncio
async def test_assisted_execution_creates_approval_not_execute(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    update = FakeUpdate(text="crea un flow de prueba")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "Aprobación requerida" in update.message.replies[-1]
    assert client.mutations == []
    rows = await store.approval_rows()
    assert rows[0]["action"] == "create_flow"
    await store.close()


@pytest.mark.asyncio
async def test_valid_confirmation_executes_mocked_mutation_only(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    update = FakeUpdate(text="crea un flow de prueba")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    code = (await store.approval_rows())[0]["code"]
    confirm = FakeUpdate(text=f"/confirm {code}")
    await dispatcher.confirm(confirm, code)
    assert client.mutations[0][0] == "create_flow"
    assert "Mutación ejecutada" in confirm.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_stale_approval_blocked_if_mode_changes(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    update = FakeUpdate(text="crea un flow")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    code = (await store.approval_rows())[0]["code"]
    dispatcher._settings.gateway_mode = "READ_ONLY"
    confirm = FakeUpdate(text=f"/confirm {code}")
    await dispatcher.confirm(confirm, code)
    assert "READ_ONLY" in confirm.message.replies[-1]
    assert client.mutations == []
    await store.close()


@pytest.mark.asyncio
async def test_wrong_user_chat_expired_approvals_do_not_execute(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    update = FakeUpdate(text="crea un flow")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    code = (await store.approval_rows())[0]["code"]
    wrong = FakeUpdate(user_id=2, chat_id=99)
    await dispatcher.confirm(wrong, code)
    assert "no pertenece" in wrong.message.replies[-1]
    await store.conn.execute("UPDATE pending_approvals SET expires_at = ?", (time.time() - 1,))
    await store.conn.commit()
    expired = FakeUpdate()
    await dispatcher.confirm(expired, code)
    assert "expirada" in expired.message.replies[-1]
    assert client.mutations == []
    await store.close()


@pytest.mark.asyncio
async def test_delete_flow_blocked_by_default(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION", admins=[1])
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(text="borra este flow")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "deshabilitado" in update.message.replies[-1]
    assert client.mutations == []
    await store.close()


@pytest.mark.asyncio
async def test_confirm_cannot_execute_delete_confirm_delete_required(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION", delete_enabled=True, admins=[1])
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(text="borra este flow")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    rows = await store.approval_rows()
    code = rows[0]["code"]
    normal = FakeUpdate(text=f"/confirm {code}")
    await dispatcher.confirm(normal, code)
    assert "confirm_delete" in normal.message.replies[-1]
    assert client.mutations == []
    special = FakeUpdate(text=f"/confirm_delete {code}")
    await dispatcher.confirm(special, code, delete=True)
    assert client.mutations[0][0] == "delete_flow"
    await store.close()


@pytest.mark.asyncio
async def test_inline_callback_goes_through_policy(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path)
    update = FakeUpdate(callback_data="crea un flow desde botón")
    await dispatcher.handle_text(update, FakeContext(), update.callback_query.data)
    assert "READ_ONLY" in update.message.replies[-1]
    assert client.mutations == []
    await store.close()
