from __future__ import annotations

from types import SimpleNamespace


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)
        self.last_reply_markup = kwargs.get("reply_markup")


class FakeCallback:
    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


class FakeUpdate:
    def __init__(self, user_id: int = 1, chat_id: int = 10, text: str = "", callback_data: str | None = None) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.message = FakeMessage(text)
        self.callback_query = FakeCallback(callback_data, self.message) if callback_data is not None else None


class FakeContext:
    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or []


class MockPentagiClient:
    def __init__(self) -> None:
        self.mutations: list[tuple[str, dict]] = []
        self.flows = [{"id": "1234", "name": "Demo", "status": "running", "updatedAt": "now"}]
        self.tasks = [{"id": "task_1", "name": "Recon", "status": "done", "result": "found safe finding"}]
        self.logs = [{"id": "log_1", "role": "assistant", "content": "Bearer should redact", "createdAt": "2026-01-01T00:00:00"}]

    async def list_providers(self):
        return [{"name": "qwen", "model": "local", "status": "connected"}]

    async def get_settings_providers(self):
        return []

    async def list_flows(self):
        return self.flows

    async def get_flow(self, flow_id):
        return {"id": flow_id, "name": "Demo", "status": "running", "updatedAt": "now"}

    async def get_tasks(self, flow_id):
        return self.tasks

    async def get_message_logs(self, flow_id, limit=None):
        return self.logs

    async def get_terminal_logs(self, flow_id, limit=None):
        return [{"id": "term", "content": "TELEGRAM_BOT_TOKEN=secret-ish", "createdAt": "now"}]

    async def create_flow(self, input_data, model_provider="qwen"):
        self.mutations.append(("create_flow", {"input": input_data, "model_provider": model_provider}))
        return {"id": "new_flow", "status": "created"}

    async def put_user_input(self, flow_id, user_input):
        self.mutations.append(("put_user_input", {"flow_id": flow_id, "input": user_input}))
        return {"id": flow_id, "status": "running"}

    async def stop_flow(self, flow_id):
        self.mutations.append(("stop_flow", {"flow_id": flow_id}))
        return {"id": flow_id, "status": "stopped"}

    async def finish_flow(self, flow_id):
        self.mutations.append(("finish_flow", {"flow_id": flow_id}))
        return {"id": flow_id, "status": "finished"}

    async def rename_flow(self, flow_id, name):
        self.mutations.append(("rename_flow", {"flow_id": flow_id, "name": name}))
        return {"id": flow_id, "name": name}

    async def delete_flow(self, flow_id):
        self.mutations.append(("delete_flow", {"flow_id": flow_id}))
        return {"deleteFlow": True}
