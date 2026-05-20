from __future__ import annotations

import pytest

from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.session import SessionStore
from gateway.llm.brain import Brain, NO_ACTIVE_FLOW_TEXT, _extract_flow_id
from gateway.llm.schemas import Intent
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


@pytest.mark.asyncio
async def test_extract_flow_id_numeric_only_explicit_patterns():
    assert _extract_flow_id("abre flow 123") == "123"
    assert _extract_flow_id("abre flujo: 456") == "456"
    assert _extract_flow_id("flow_id=789") == "789"
    assert _extract_flow_id("id #321") == "321"
    assert _extract_flow_id("abre este flow demo") is None


@pytest.mark.asyncio
async def test_brain_never_infers_normal_words_as_flow_id():
    decision = await Brain().classify("abre este flow demo")
    assert decision.intent is Intent.UNKNOWN
    assert decision.flow_ref is None


@pytest.mark.asyncio
async def test_no_active_status_summary_findings_guidance():
    brain = Brain()
    for text in ("qué está haciendo", "resume el flow", "qué encontró"):
        decision = await brain.classify(text, active_flow_id=None)
        assert decision.intent is Intent.UNKNOWN
        assert decision.user_response == NO_ACTIVE_FLOW_TEXT


@pytest.mark.asyncio
async def test_non_digit_active_flow_id_still_routes_with_flow_ref(tmp_path):
    """Non-digit flow_id is stored and used; the brain does not reject it."""
    store = SessionStore(str(tmp_path / "guard.sqlite"))
    await store.open()
    dispatcher = Dispatcher(AuthProvider([1]), store, client=MockPentagiClient())
    await store.bind_flow(10, 1, "flow_demo")
    update = FakeUpdate(text="qué está haciendo")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    # With an active flow (even non-numeric), the dispatcher should proceed
    assert "Demo" in update.message.replies[-1] or "Resumen" in update.message.replies[-1]
    assert NO_ACTIVE_FLOW_TEXT not in update.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_stop_local_clears_session_without_mutation(tmp_path):
    store = SessionStore(str(tmp_path / "stop.sqlite"))
    await store.open()
    client = MockPentagiClient()
    dispatcher = Dispatcher(AuthProvider([1]), store, client=client)
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(callback_data="ui:stop_local")
    await dispatcher.handle_command_action(update, FakeContext(), "stop_local")
    session = await store.get_session(10, 1)
    assert session is not None
    assert session.active_flow_id is None
    assert client.mutations == []
    assert "No se ejecutó ninguna acción" in update.message.replies[-1]
    await store.close()
