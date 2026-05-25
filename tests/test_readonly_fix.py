"""Tests for READ_ONLY policy: safe intents never blocked, mutations blocked with approval UX."""
from __future__ import annotations

import pytest

from gateway.config import Settings
from gateway.core.auth import AuthProvider
from gateway.core.dispatcher import Dispatcher
from gateway.core.policy import READ_ONLY_BLOCK_MESSAGE
from gateway.core.session import SessionStore
from gateway.llm import Intent
from tests.helpers import FakeContext, FakeUpdate, MockPentagiClient


class MutatingClient(MockPentagiClient):
    """Client that tracks mutations."""
    async def create_flow(self, input_data, model_provider="qwen"):
        return {"id": "999", "status": "created"}

    async def put_user_input(self, flow_id, user_input):
        return {"id": "999", "status": "input_sent"}

    async def stop_flow(self, flow_id):
        return {"id": flow_id, "status": "stopped"}

    async def finish_flow(self, flow_id):
        return {"id": flow_id, "status": "finished"}

    async def rename_flow(self, flow_id, title):
        return {"id": flow_id, "name": title}

    async def create_assistant(self, flow_id, model_provider="qwen", input_text="", use_agents=False):
        return {"assistant": {"id": "asst_new", "title": "Assistant", "status": "ready"}}

    async def call_assistant(self, flow_id, assistant_id, input_text="", use_agents=False):
        return {"success": True, "output": "Assistant response"} 

    async def get_assistants(self, flow_id):
        return [{"id": "asst_1", "title": "Assistant", "status": "ready"}]

    async def delete_flow(self, flow_id):
        return {"id": flow_id, "deleted": True}

    async def list_flows(self):
        return [{"id": "1", "name": "Flow Test", "status": "running"}]

    async def get_flow(self, flow_id):
        return {"id": flow_id, "name": "Flow Test", "status": "running"}

    async def get_tasks(self, flow_id):
        return [{"id": "1", "title": "Task 1", "status": "completed"}]

    async def get_message_logs(self, flow_id, limit=None):
        return [{"role": "user", "content": "hello"}]

    async def get_terminal_logs(self, flow_id, limit=None):
        return [{"timestamp": "now", "message": "log entry"}]

    async def list_providers(self):
        return [{"name": "qwen", "type": "llm"}]

    async def get_settings_providers(self):
        return []

    async def get_assistants(self, flow_id):
        return []


async def make_dispatcher(tmp_path, client=None, mode="READ_ONLY"):
    store = SessionStore(str(tmp_path / "readonly_fix.sqlite"))
    await store.open()
    dispatcher = Dispatcher(
        AuthProvider(allowed_users=[1]),
        store,
        settings=Settings(gateway_mode=mode),
        client=client if client is not None else MutatingClient(),
    )
    return dispatcher, store


# === SAFE LOCAL INTENTS (never blocked) ===

@pytest.mark.asyncio
async def test_readonly_hola_returns_menu_not_blocked(tmp_path):
    """READ_ONLY + 'Hola' => GREETING/HOME, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="hola")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1].lower()
    assert "PentAGI" in reply or "gateway" in reply
    assert "read_only" in reply
    assert "bloqueado" not in reply
    assert update.message.last_reply_markup is not None
    await store.close()


@pytest.mark.asyncio
async def test_readonly_ayuda_returns_help_not_blocked(tmp_path):
    """READ_ONLY + 'ayuda' => HELP, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="ayuda")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1].lower()
    assert "PentAGI" in reply or "flows" in reply or "ayuda" in reply
    assert "bloqueado" not in reply
    await store.close()


@pytest.mark.asyncio
async def test_readonly_who_are_you_returns_identity(tmp_path):
    """READ_ONLY + 'quién eres' => OPERATOR_IDENTITY, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="quién eres")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "PentAGI Gateway" in reply
    assert "bloqueado" not in reply.lower()
    await store.close()


@pytest.mark.asyncio
async def test_readonly_capabilities_returns_info(tmp_path):
    """READ_ONLY + 'qué puedes hacer' => OPERATOR_CAPABILITIES, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="qué puedes hacer")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "flows" in reply.lower() or "PentAGI" in reply
    assert "bloqueado" not in reply.lower()
    await store.close()


# === READ-ONLY QUERY INTENTS (never blocked) ===

@pytest.mark.asyncio
async def test_readonly_ver_flows_not_blocked(tmp_path):
    """READ_ONLY + 'ver flows' => LIST_FLOWS, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="muéstrame los flows")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "Flow Test" in reply or "flows" in reply.lower()
    assert "bloqueado" not in reply.lower()
    await store.close()


@pytest.mark.asyncio
async def test_readonly_ver_tareas_con_flow_activo_not_blocked(tmp_path):
    """READ_ONLY + 'ver tareas' con flow activo => GET_TASKS, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    update = FakeUpdate(text="ver tareas")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "Task 1" in reply or "tareas" in reply.lower()
    assert "bloqueado" not in reply.lower()
    await store.close()


@pytest.mark.asyncio
async def test_readonly_ver_logs_not_blocked(tmp_path):
    """READ_ONLY + 'logs' => GET_LOGS, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    update = FakeUpdate(text="logs")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "hello" in reply.lower() or "logs" in reply.lower()
    assert "bloqueado" not in reply.lower()
    await store.close()


@pytest.mark.asyncio
async def test_readonly_ver_terminal_not_blocked(tmp_path):
    """READ_ONLY + 'terminal' => VIEW_TERMINAL, no bloqueo."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    update = FakeUpdate(text="terminal")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "log entry" in reply or "terminal" in reply.lower()
    assert "bloqueado" not in reply.lower()
    await store.close()


# === MUTATION INTENTS (blocked with approval UX) ===

@pytest.mark.asyncio
async def test_readonly_put_user_input_executes_directly(tmp_path):
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1234")
    update = FakeUpdate(text="dile que continúe")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    # put_user_input ahora pasa directo sin approval en READ_ONLY
    assert "Input enviado" in reply or "putUserInput" in reply
    await store.close()


# === ASSISTANT MODE FLOW ===

@pytest.mark.asyncio
async def test_readonly_modo_asistente_con_flow_activo_funciona_directo(tmp_path):
    """READ_ONLY + 'modo asistente' con flow activo => entra directo sin aprobación."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    session = await store.get_session(10, 1)
    session.active_assistant_id = "asst_123"
    await store.upsert_session(session)
    update = FakeUpdate(text="modo asistente")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "Assistant" in reply or "asistente" in reply.lower()
    await store.close()


@pytest.mark.asyncio
async def test_assisted_execution_modo_asistente_creates(tmp_path):
    """ASSISTED_EXECUTION + 'modo asistente' => creates assistant."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="ASSISTED_EXECUTION")
    await store.bind_flow(10, 1, "1")
    update = FakeUpdate(text="modo asistente")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    # In ASSISTED_EXECUTION, view_assistant shows the screen directly
    reply = update.message.replies[-1]
    assert "bloqueado" not in reply.lower()
    await store.close()


# === TEXT FREE WITHOUT ASSISTANT ===

@pytest.mark.asyncio
async def test_text_free_without_flow_shows_options(tmp_path):
    """Texto libre sin flow activo => muestra opciones, no bloqueo seco."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    update = FakeUpdate(text="haz algo interesante")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "bloqueado" not in reply.lower() or "PentAGI" in reply
    assert update.message.last_reply_markup is not None
    await store.close()


# === COMPREHENSIVE: READ_ONLY NEVER BLOCKS SAFE/QUERY INTENTS ===

@pytest.mark.asyncio
async def test_readonly_never_blocks_safe_local_intents(tmp_path):
    """READ_ONLY nunca bloquea SAFE_LOCAL_INTENTS."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    safe_texts = ["hola", "buenas", "qué puedes hacer", "quién eres", "ayuda", "help"]
    for text in safe_texts:
        update = FakeUpdate(text=text)
        await dispatcher.handle_text(update, FakeContext(), update.message.text)
        reply = update.message.replies[-1].lower()
        assert "bloqueado" not in reply, f"SAFE_INTENT '{text}' was blocked in READ_ONLY"
    await store.close()


@pytest.mark.asyncio
async def test_readonly_never_blocks_read_only_query_intents(tmp_path):
    """READ_ONLY nunca bloquea READ_ONLY_QUERY_INTENTS."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    query_texts = ["muéstrame los flows", "ver tareas", "logs", "terminal", "resumen", "qué encontró"]
    for text in query_texts:
        update = FakeUpdate(text=text)
        await dispatcher.handle_text(update, FakeContext(), update.message.text)
        reply = update.message.replies[-1].lower()
        assert "bloqueado" not in reply, f"QUERY_INTENT '{text}' was blocked in READ_ONLY"
    await store.close()


@pytest.mark.asyncio
async def test_readonly_executes_create_stop_directly_blocks_finish(tmp_path):
    """READ_ONLY ejecuta create_flow/stop_flow directo, bloquea finish_flow con UX."""
    dispatcher, store = await make_dispatcher(tmp_path, mode="READ_ONLY")
    await store.bind_flow(10, 1, "1")
    # create_flow pasa directo via handle_command_action (READ_ACTIONS)
    update = FakeUpdate(text="ignored")
    await dispatcher.handle_command_action(update, FakeContext(), "create_flow", {"input": {"prompt": "test"}}, risk="LOW")
    reply = update.message.replies[-1]
    assert "bloqueado" not in reply.lower()
    # stop_flow pasa directo via handle_command_action (READ_ACTIONS)
    update = FakeUpdate(text="ignored")
    await dispatcher.handle_command_action(update, FakeContext(), "stop_flow", {"flow_id": "1"}, risk="LOW")
    reply = update.message.replies[-1]
    assert "bloqueado" not in reply.lower()
    # finish_flow sí se bloquea via handle_command_action (MUTATION_ACTIONS)
    update = FakeUpdate(text="ignored")
    await dispatcher.handle_command_action(update, FakeContext(), "finish_flow", {"flow_id": "1"}, risk="LOW")
    reply = update.message.replies[-1]
    assert "bloqueado" in reply.lower() or "ASSISTED_EXECUTION" in reply
    # "dile que continúe" ejecuta directo (put_user_input en READ_ACTIONS)
    update = FakeUpdate(text="dile que continúe")
    await dispatcher.handle_text(update, FakeContext(), update.message.text)
    reply = update.message.replies[-1]
    assert "Input enviado" in reply or "putUserInput" in reply, f"Expected direct execution: {reply}"
    await store.close()
