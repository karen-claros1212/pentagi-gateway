"""Test suite for patch 8 — UI State Machine Adapter.

Tests cover:
- Session UI fields (creation, save, load, migration)
- Brain with enriched context (new intents)
- Formatter screens (each screen function)
- Dispatcher snapshot (mock PentagiClient)
- Text handler routing by screen state
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Settings
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.session import SessionStore, TelegramSession
from gateway.llm import Brain, Intent
from gateway.llm.brain import BrainContext
from gateway.llm.schemas import IntentDecision
from gateway.telegram.formatter import (
    active_flow_running_screen,
    assistant_screen,
    error_screen,
    flow_finished_screen,
    flow_waiting_screen,
    home_screen,
    new_flow_draft_screen,
    provider_select_screen,
    template_select_screen,
)
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


# =========================================================================
# 1. Session UI Fields
# =========================================================================


@pytest.mark.asyncio
async def test_session_ui_fields_creation(tmp_path):
    """New session should have default UI field values."""
    store = SessionStore(str(tmp_path / "ui_test.sqlite"))
    await store.open()

    s = TelegramSession(chat_id=1, user_id=100, role="readonly")
    assert s.active_flow_status is None
    assert s.selected_provider is None
    assert s.selected_assistant_id is None
    assert s.draft_message is None
    assert s.draft_template_id is None
    assert s.last_screen == "home"
    assert s.last_snapshot_at is None

    await store.upsert_session(s)
    got = await store.get_session(1, 100)
    assert got is not None
    assert got.last_screen == "home"
    assert got.active_flow_status is None

    await store.close()


@pytest.mark.asyncio
async def test_session_ui_fields_save_load(tmp_path):
    """UI fields should persist through upsert/get cycle."""
    store = SessionStore(str(tmp_path / "ui_test2.sqlite"))
    await store.open()

    s = TelegramSession(
        chat_id=10, user_id=200, role="admin",
        active_flow_status="running",
        selected_provider="qwen",
        selected_assistant_id="ast-1",
        draft_message="auditar servidor",
        draft_template_id="tpl-1",
        last_screen="new_flow_draft",
        last_snapshot_at=time.time(),
    )
    await store.upsert_session(s)

    got = await store.get_session(10, 200)
    assert got.active_flow_status == "running"
    assert got.selected_provider == "qwen"
    assert got.selected_assistant_id == "ast-1"
    assert got.draft_message == "auditar servidor"
    assert got.draft_template_id == "tpl-1"
    assert got.last_screen == "new_flow_draft"
    assert got.last_snapshot_at > 0

    await store.close()


@pytest.mark.asyncio
async def test_session_ui_fields_update(tmp_path):
    """Updating UI fields should persist changes."""
    store = SessionStore(str(tmp_path) + "/ui_test3.sqlite")
    await store.open()

    s = TelegramSession(chat_id=1, user_id=300, role="readonly")
    await store.upsert_session(s)

    s.active_flow_status = "waiting"
    s.draft_message = "nuevo objetivo"
    await store.upsert_session(s)

    got = await store.get_session(1, 300)
    assert got.active_flow_status == "waiting"
    assert got.draft_message == "nuevo objetivo"

    await store.close()


@pytest.mark.asyncio
async def test_session_backward_compat(tmp_path):
    """Existing sessions (without UI fields) should still work."""
    store = SessionStore(str(tmp_path / "compat.sqlite"))
    await store.open()

    # Insert old-style row directly
    await store.conn.execute(
        "INSERT INTO telegram_sessions (chat_id, user_id, role, mode, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (99, 999, "readonly", "READ_ONLY", time.time(), time.time()),
    )
    await store.conn.commit()

    got = await store.get_session(99, 999)
    assert got is not None
    assert got.chat_id == 99
    assert got.user_id == 999
    assert got.last_screen == "home"  # default from dataclass

    await store.close()


# =========================================================================
# 2. Brain — New Intents with Context
# =========================================================================


async def _make_brain() -> Brain:
    return Brain(enabled=False)


@pytest.mark.asyncio
async def test_brain_new_intent_set_provider():
    brain = await _make_brain()
    ctx = BrainContext(providers=[{"name": "qwen"}, {"name": "openai"}], last_screen="home")
    d = await brain.classify("seleccionar proveedor qwen", context=ctx)
    assert d.intent == Intent.SET_PROVIDER


@pytest.mark.asyncio
async def test_brain_new_intent_apply_template():
    brain = await _make_brain()
    d = await brain.classify("aplicar plantilla tpl-audit", context=BrainContext())
    assert d.intent == Intent.APPLY_TEMPLATE
    assert d.parameters.get("template_id") == "tpl-audit"


@pytest.mark.asyncio
async def test_brain_new_intent_submit_draft():
    brain = await _make_brain()
    d = await brain.classify("nuevo flow para pentest", context=BrainContext())
    assert d.intent == Intent.SUBMIT_DRAFT


@pytest.mark.asyncio
async def test_brain_new_intent_view_terminal():
    brain = await _make_brain()
    ctx = BrainContext(active_flow_id="123")
    d = await brain.classify("ver terminal", context=ctx)
    assert d.intent == Intent.VIEW_TERMINAL


@pytest.mark.asyncio
async def test_brain_new_intent_view_assistant():
    brain = await _make_brain()
    d = await brain.classify("asistente", context=BrainContext())
    assert d.intent == Intent.VIEW_ASSISTANT


@pytest.mark.asyncio
async def test_brain_new_intent_send_assistant_message():
    brain = await _make_brain()
    d = await brain.classify("envía al assistant que revise el log", context=BrainContext())
    assert d.intent == Intent.SEND_ASSISTANT_MESSAGE


@pytest.mark.asyncio
async def test_brain_help_ui_contextual():
    brain = await _make_brain()
    ctx = BrainContext(last_screen="new_flow_draft")
    d = await brain.classify("ayuda", context=ctx)
    assert d.intent == Intent.HELP_UI
    assert d.parameters.get("screen") == "new_flow_draft"


@pytest.mark.asyncio
async def test_brain_help_global_on_home():
    brain = await _make_brain()
    ctx = BrainContext(last_screen="home")
    d = await brain.classify("ayuda", context=ctx)
    assert d.intent == Intent.HELP  # global help on home screen


@pytest.mark.asyncio
async def test_brain_existing_intents_still_work():
    brain = await _make_brain()
    d = await brain.classify("muéstrame los flows")
    assert d.intent == Intent.LIST_FLOWS

    d2 = await brain.classify("mostrar providers")
    assert d2.intent == Intent.LIST_PROVIDERS

    d3 = await brain.classify("crea un flow para auditar", active_flow_id="123")
    assert d3.intent == Intent.SUBMIT_DRAFT  # matches "crear flow"

    d4 = await brain.classify("detén el flow", active_flow_id="123")
    assert d4.intent == Intent.STOP_FLOW_REQUEST


@pytest.mark.asyncio
async def test_brain_no_text():
    brain = await _make_brain()
    d = await brain.classify("")
    assert d.intent == Intent.UNKNOWN


# =========================================================================
# 3. Formatter Screens
# =========================================================================


def _make_session(**kwargs) -> TelegramSession:
    defaults = dict(chat_id=1, user_id=100, role="readonly")
    defaults.update(kwargs)
    return TelegramSession(**defaults)


def test_home_screen_with_active_flow():
    session = _make_session(active_flow_id="1234", active_flow_status="running")
    text, markup = home_screen(session, [], [])
    assert "PentAGI Gateway" in text
    assert "1234" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:new_flow" in callbacks
    assert "ui:status" in callbacks
    assert "ui:stop_flow" in callbacks


def test_home_screen_no_active_flow():
    session = _make_session()
    text, markup = home_screen(session, [], [])
    assert "Sin flow activo" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:status" not in callbacks
    assert "ui:new_flow" in callbacks


def test_new_flow_draft_screen():
    session = _make_session(draft_message="auditar servidor", selected_provider="qwen")
    text, markup = new_flow_draft_screen(session, [], [])
    assert "Nuevo Flow" in text
    assert "auditar servidor" in text
    assert "qwen" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:submit_draft" in callbacks
    assert "ui:home" in callbacks


def test_new_flow_draft_screen_empty():
    session = _make_session()
    text, markup = new_flow_draft_screen(session, [], [])
    assert "Escribe tu objetivo" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:submit_draft" not in callbacks


def test_active_flow_running_screen():
    session = _make_session(active_flow_id="5678", active_flow_status="running")
    flow = {"title": "Audit", "status": "running"}
    tasks = [{"id": "t1", "title": "Recon", "status": "done", "result": "OK"}]
    logs = [{"role": "assistant", "content": "Scanning", "createdAt": "now"}]
    text, markup = active_flow_running_screen(flow, tasks, logs, session)
    assert "Audit" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:terminal" in callbacks
    assert "ui:tasks" in callbacks
    assert "ui:stop_flow" in callbacks
    assert "ui:home" in callbacks


def test_flow_waiting_screen():
    session = _make_session(active_flow_id="9012")
    flow = {"title": "Pentest", "status": "waiting"}
    text, markup = flow_waiting_screen(flow, session)
    assert "espera tu input" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:input" in callbacks


def test_flow_finished_screen():
    flow = {"title": "Scan", "status": "finished"}
    tasks = [{"id": "t1", "result": "vulnerabilidad XSS"}, {"id": "t2", "result": "puerto 80 abierto"}]
    text, markup = flow_finished_screen(flow, tasks)
    assert "completado" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:new_flow" in callbacks
    assert "ui:home" in callbacks


def test_assistant_screen_empty():
    text, markup = assistant_screen([], [])
    assert "Asistente" in text
    assert "Escribe tu mensaje" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:home" in callbacks


def test_assistant_screen_with_logs():
    logs = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "hola en qué puedo ayudar"}]
    text, markup = assistant_screen([], logs)
    assert "hola" in text
    assert "ayudar" in text


def test_provider_select_screen():
    providers = [{"name": "qwen", "type": "local"}, {"name": "openai", "type": "api"}]
    text, markup = provider_select_screen(providers, "qwen")
    assert "Selecciona un Provider" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:select_provider:qwen (local)" in callbacks
    assert "ui:home" in callbacks


def test_provider_select_screen_empty():
    text, markup = provider_select_screen([], None)
    assert "No hay providers" in text


def test_template_select_screen():
    templates = [{"id": "tpl-1", "name": "Pentest Rápido"}, {"id": "tpl-2", "name": "Audit Completo"}]
    text, markup = template_select_screen(templates, "tpl-1")
    assert "Selecciona un Template" in text
    callbacks = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert "ui:select_template:tpl-1" in callbacks
    assert "ui:home" in callbacks


def test_template_select_screen_empty():
    text, markup = template_select_screen([], None)
    assert "Selecciona un Template" in text
    assert "ninguno" in text


def test_error_screen():
    msg = error_screen("ConnectionError: timeout connecting to PentAGI at localhost:8443")
    assert "Error" in msg
    assert "Traceback" not in msg


# =========================================================================
# 4. Dispatcher Snapshot
# =========================================================================


@pytest.mark.asyncio
async def test_dispatcher_snapshot_flow_status(tmp_path):
    """Dispatcher should take a snapshot and update session fields."""
    store = SessionStore(str(tmp_path / "snapshot.sqlite"))
    await store.open()

    session = TelegramSession(chat_id=10, user_id=1, active_flow_id="1234")
    await store.upsert_session(session)

    client = MockPentagiClient()
    # Override get_flow to return status
    client.get_flow = AsyncMock(return_value={
        "id": "1234", "name": "Test", "status": "running",
        "provider": {"name": "qwen"},
    })

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=client,
    )

    await dispatcher._take_snapshot(session)
    assert session.active_flow_status == "running"
    assert session.selected_provider == "qwen"
    assert session.last_snapshot_at is not None

    got = await store.get_session(10, 1)
    assert got.active_flow_status == "running"

    await store.close()


@pytest.mark.asyncio
async def test_dispatcher_snapshot_no_active_flow(tmp_path):
    """Snapshot should be a no-op without active flow."""
    store = SessionStore(str(tmp_path / "snapshot2.sqlite"))
    await store.open()

    session = TelegramSession(chat_id=10, user_id=1)
    await store.upsert_session(session)

    client = MockPentagiClient()
    get_flow_mock = AsyncMock()
    client.get_flow = get_flow_mock

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=client,
    )

    await dispatcher._take_snapshot(session)
    get_flow_mock.assert_not_called()

    await store.close()


@pytest.mark.asyncio
async def test_dispatcher_snapshot_failure_graceful(tmp_path):
    """Snapshot failure should not crash the dispatcher."""
    store = SessionStore(str(tmp_path / "snapshot3.sqlite"))
    await store.open()

    session = TelegramSession(chat_id=10, user_id=1, active_flow_id="9999")
    await store.upsert_session(session)

    client = MockPentagiClient()
    client.get_flow = AsyncMock(side_effect=Exception("API down"))

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=client,
    )

    # Should not raise
    await dispatcher._take_snapshot(session)

    await store.close()


# =========================================================================
# 5. Text Handler Routing by Screen State
# =========================================================================


@pytest.mark.asyncio
async def test_text_handler_draft_routing(tmp_path):
    """Text should be treated as draft message when last_screen is new_flow_draft."""
    store = SessionStore(str(tmp_path / "route1.sqlite"))
    await store.open()

    session = TelegramSession(chat_id=10, user_id=1, last_screen="new_flow_draft", draft_message="")
    await store.upsert_session(session)

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    update = FakeUpdate(user_id=1, chat_id=10, text="auditar servidor linux")
    await dispatcher.handle_text(update, FakeContext(), "auditar servidor linux")

    # Should have updated draft_message in session
    got = await store.get_session(10, 1)
    # In READ_ONLY, submit_draft blocks with message
    assert "READ_ONLY" in update.message.replies[-1]

    await store.close()


@pytest.mark.asyncio
async def test_text_handler_waiting_flow_routing(tmp_path):
    """Text should be treated as flow input when flow status is waiting."""
    store = SessionStore(str(tmp_path / "route2.sqlite"))
    await store.open()

    session = TelegramSession(
        chat_id=10, user_id=1,
        active_flow_id="1234",
        active_flow_status="waiting",
    )
    await store.upsert_session(session)

    client = MockPentagiClient()

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="ASSISTED_EXECUTION"),
        client=client,
    )

    update = FakeUpdate(user_id=1, chat_id=10, text="sí, continúa con el escaneo")
    await dispatcher.handle_text(update, FakeContext(), "sí, continúa con el escaneo")

    # Should create an approval for put_user_input
    assert "Aprobación requerida" in update.message.replies[-1]

    await store.close()


@pytest.mark.asyncio
async def test_text_handler_assistant_routing(tmp_path):
    """Text should be treated as assistant message when last_screen is assistant."""
    store = SessionStore(str(tmp_path / "route3.sqlite"))
    await store.open()

    session = TelegramSession(
        chat_id=10, user_id=1,
        last_screen="assistant",
        selected_assistant_id="ast-1",
    )
    await store.upsert_session(session)

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    update = FakeUpdate(user_id=1, chat_id=10, text="explica el hallazgo")
    await dispatcher.handle_text(update, FakeContext(), "explica el hallazgo")

    assert "Assistant" in update.message.replies[-1] or "READ_ONLY" in update.message.replies[-1]

    await store.close()


@pytest.mark.asyncio
async def test_text_handler_normal_classify_when_no_context(tmp_path):
    """Without draft/waiting/assistant context, text goes through brain classify."""
    store = SessionStore(str(tmp_path / "route4.sqlite"))
    await store.open()

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    update = FakeUpdate(user_id=1, chat_id=10, text="muéstrame los flows")
    await dispatcher.handle_text(update, FakeContext(), "muéstrame los flows")

    assert "PentAGI Flows" in update.message.replies[-1]

    await store.close()


# =========================================================================
# 6. Dispatcher handle_command_action with UI actions
# =========================================================================


@pytest.mark.asyncio
async def test_command_action_set_provider(tmp_path):
    """handle_command_action should delegate set_provider to screen routing."""
    store = SessionStore(str(tmp_path / "ui_action.sqlite"))
    await store.open()

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    update = FakeUpdate(user_id=1, chat_id=10)
    await dispatcher.handle_command_action(update, FakeContext(), "set_provider", {"provider": "qwen"})

    got = await store.get_session(10, 1)
    assert got.selected_provider == "qwen"

    await store.close()


@pytest.mark.asyncio
async def test_command_action_apply_template(tmp_path):
    """handle_command_action should set draft_template_id."""
    store = SessionStore(str(tmp_path / "ui_action2.sqlite"))
    await store.open()

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    update = FakeUpdate(user_id=1, chat_id=10)
    await dispatcher.handle_command_action(update, FakeContext(), "apply_template", {"template_id": "tpl-audit"})

    got = await store.get_session(10, 1)
    assert got.draft_template_id == "tpl-audit"

    await store.close()


@pytest.mark.asyncio
async def test_brain_context_enriched_with_snapshot_data(tmp_path):
    """BrainContext built by dispatcher includes snapshot data."""
    store = SessionStore(str(tmp_path / "ctx.sqlite"))
    await store.open()

    session = TelegramSession(
        chat_id=10, user_id=1,
        active_flow_id="1234",
        active_flow_status="running",
        selected_provider="qwen",
        last_screen="home",
    )
    await store.upsert_session(session)

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=MockPentagiClient(),
    )

    ctx = await dispatcher._build_brain_context(session)
    assert ctx.flow_status == "running"
    assert ctx.active_flow_id == "1234"
    assert ctx.gateway_mode == "READ_ONLY"
    assert ctx.last_screen == "home"
    assert ctx.selected_provider == "qwen"

    await store.close()


@pytest.mark.asyncio
async def test_dispatcher_handle_text_snapshot_before_classify(tmp_path):
    """handle_text should snapshot active flow before brain classify."""
    store = SessionStore(str(tmp_path / "snapshot_route.sqlite"))
    await store.open()

    session = TelegramSession(chat_id=10, user_id=1, active_flow_id="1234")
    await store.upsert_session(session)

    client = MockPentagiClient()
    client.get_flow = AsyncMock(return_value={
        "id": "1234", "name": "Test", "status": "running",
        "provider": {"name": "qwen"},
    })

    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=client,
    )

    update = FakeUpdate(user_id=1, chat_id=10, text="qué está haciendo")
    await dispatcher.handle_text(update, FakeContext(), "qué está haciendo")

    got = await store.get_session(10, 1)
    assert got.active_flow_status == "running"

    await store.close()
