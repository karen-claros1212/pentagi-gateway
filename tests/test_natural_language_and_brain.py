from __future__ import annotations

import pytest

from gateway.config import Settings
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.session import SessionStore
from gateway.llm import Brain, Intent
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


async def make_dispatcher(tmp_path, mode="READ_ONLY"):
    store = SessionStore(str(tmp_path / "nl.sqlite"))
    await store.open()
    client = MockPentagiClient()
    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode=mode),
        client=client,
    )
    return dispatcher, store, client


@pytest.mark.asyncio
async def test_natural_language_list_flows(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path)
    update = FakeUpdate(text="muéstrame los flows")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "PentAGI Flows" in update.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_active_flow_status_summary_and_findings(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path)
    await store.bind_flow(10, 1, "1234")
    for text, expected in [
        ("qué está haciendo", "Resumen"),
        ("resume el flow", "Resumen"),
        ("qué encontró", "Hallazgos"),
    ]:
        update = FakeUpdate(text=text)
        await dispatcher.handle_text(update, FakeContext(), text)
        assert expected in update.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_create_flow_and_send_input_require_approval(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    update = FakeUpdate(text="crea un flow para auditar")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "Aprobación requerida" in update.message.replies[-1]
    await store.bind_flow(10, 1, "1234")
    send = FakeUpdate(text="dile que continúe")
    await dispatcher.handle_text(send, FakeContext(), send.message.text)
    assert "Aprobación requerida" in send.message.replies[-1]
    assert client.mutations == []
    await store.close()


@pytest.mark.asyncio
async def test_ambiguous_clarification_and_delete_blocked(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path)
    update = FakeUpdate(text="haz eso")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "No entendí" in update.message.replies[-1]
    delete = FakeUpdate(text="delete todo")
    await dispatcher.handle_text(delete, FakeContext(), delete.message.text)
    assert "READ_ONLY" in delete.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_llm_invalid_json_unknown(monkeypatch):
    async def fake_post(*args, **kwargs):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "not-json"}}]}

        return Resp()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        post = fake_post

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())
    decision = await Brain(enabled=True).classify("crea flow")
    assert decision.intent is Intent.UNKNOWN


@pytest.mark.asyncio
async def test_llm_cannot_bypass_policy_direct_execute(tmp_path):
    class UnsafeBrain:
        async def classify(self, text, active_flow_id=None):
            from gateway.llm.schemas import IntentDecision

            return IntentDecision(intent="CREATE_FLOW_REQUEST", risk="LOW", requires_confirmation=False, action="create_flow")

    store = SessionStore(str(tmp_path / "llm.sqlite"))
    await store.open()
    client = MockPentagiClient()
    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode="READ_ONLY"),
        client=client,
        brain=UnsafeBrain(),
    )
    update = FakeUpdate(text="unsafe")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "READ_ONLY" in update.message.replies[-1]
    assert client.mutations == []
    await store.close()
