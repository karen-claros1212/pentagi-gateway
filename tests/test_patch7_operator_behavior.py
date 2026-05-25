from __future__ import annotations

import pytest

from gateway.config import Settings
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.policy import READ_ONLY_BLOCK_MESSAGE
from gateway.core.session import SessionStore
from gateway.llm import Brain, Intent
from gateway.telegram.formatter import format_safe_error, main_menu_markup
from gateway.telegram.handlers import CommandHandlers
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


class ExplodingClient(MockPentagiClient):
    async def list_flows(self):  # pragma: no cover - should not be reached by intro tests
        raise AssertionError("PentAGI should not be called")

    async def list_providers(self):  # pragma: no cover
        raise AssertionError("PentAGI should not be called")

    async def get_flow(self, flow_id):  # pragma: no cover
        raise AssertionError("PentAGI should not be called")


class StateClient(MockPentagiClient):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status

    async def get_flow(self, flow_id):
        return {"id": flow_id, "name": "Operación", "status": self.status, "updatedAt": "now"}


class ErrorClient(MockPentagiClient):
    async def list_flows(self):
        raise RuntimeError("GraphQL errors: ['strconv.ParseInt token=abc Bearer secret traceback line 1']")


async def make_dispatcher(tmp_path, client=None, mode="READ_ONLY"):
    store = SessionStore(str(tmp_path / "operator.sqlite"))
    await store.open()
    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode=mode),
        client=client if client is not None else MockPentagiClient(),
    )
    return dispatcher, store, dispatcher._client


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["hola", "buenas"])
async def test_brain_greeting_intro_no_flow_id_no_mutation(text):
    decision = await Brain(enabled=False).classify(text)
    assert decision.intent is Intent.GREETING
    assert decision.flow_ref is None
    assert not decision.requires_confirmation
    assert "PentAGI Gateway" in decision.user_response


@pytest.mark.asyncio
async def test_brain_identity_no_flow_id_no_mutation():
    decision = await Brain(enabled=False).classify("quién eres")
    assert decision.intent is Intent.OPERATOR_IDENTITY
    assert decision.flow_ref is None
    assert not decision.requires_confirmation
    assert "operadora" in decision.user_response or "Gateway" in decision.user_response


@pytest.mark.asyncio
async def test_brain_capabilities_no_mutation():
    decision = await Brain(enabled=False).classify("qué puedes hacer")
    assert decision.intent is Intent.OPERATOR_CAPABILITIES
    assert not decision.requires_confirmation
    assert "flows" in decision.user_response


@pytest.mark.asyncio
async def test_dispatcher_hola_does_not_call_pentagi(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path, client=ExplodingClient())
    update = FakeUpdate(text="hola")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "PentAGI Gateway" in update.message.replies[-1] or "operador" in update.message.replies[-1].lower()
    assert update.message.last_reply_markup is not None
    await store.close()


@pytest.mark.asyncio
async def test_dispatcher_identity_does_not_call_pentagi(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path, client=ExplodingClient())
    update = FakeUpdate(text="quién eres")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "PentAGI Gateway" in update.message.replies[-1]
    assert update.message.last_reply_markup is not None
    await store.close()


@pytest.mark.asyncio
async def test_no_active_flow_activity_query_offers_selection_not_command_fallback(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path)
    update = FakeUpdate(text="quién está trabajando ahora")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "flow activo" in reply
    assert "flows disponibles" in reply
    assert "/flows" not in reply
    assert update.message.last_reply_markup is not None
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [
        ("running", "marcha"),
        ("waiting_user_input", "READ_ONLY"),
        ("finished", "reporte"),
    ],
)
async def test_active_flow_state_formatting(tmp_path, status, expected):
    dispatcher, store, _client = await make_dispatcher(tmp_path, client=StateClient(status))
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(text="estado")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert expected in update.message.replies[-1]
    assert update.message.last_reply_markup is not None
    await store.close()


@pytest.mark.asyncio
async def test_sensitive_action_readonly_blocked_no_mutation(tmp_path):
    dispatcher, store, client = await make_dispatcher(tmp_path)
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(text="dile que continúe")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    assert "Input enviado" in update.message.replies[-1]
    await store.close()


@pytest.mark.asyncio
async def test_graphql_error_formatting_no_traceback_no_secret(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path, client=ErrorClient())
    update = FakeUpdate(text="muéstrame los flows")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "PentAGI rechazó" in reply
    assert "traceback" not in reply.lower()
    assert "Bearer" not in reply
    assert "secret" not in reply.lower()
    await store.close()


def test_main_menu_contains_operator_routes():
    markup = main_menu_markup()
    labels = [button.text for row in markup.inline_keyboard for button in row]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    for label in ["Ver flows", "Estado gateway", "Providers", "Ayuda", "Resumen", "Tareas", "Logs", "Terminal", "Hallazgos", "Stop local", "Enviar instrucción"]:
        assert label in labels
    assert "ui:send_input_help" in callbacks


@pytest.mark.asyncio
async def test_callbacks_route_through_dispatcher_policy(tmp_path):
    dispatcher, store, _client = await make_dispatcher(tmp_path)
    handler = CommandHandlers(MockPentagiClient(), dispatcher)
    update = FakeUpdate(callback_data="ui:send_input_help")
    await handler.callback(update, FakeContext())
    assert update.callback_query.answered is True
    assert "READ_ONLY" in update.message.replies[-1]
    await store.close()


def test_safe_error_humanized():
    text = format_safe_error(RuntimeError("Traceback... API token rejected (401) Bearer abc"))
    assert "autenticar" in text
    assert "Bearer" not in text
    assert "Traceback" not in text
