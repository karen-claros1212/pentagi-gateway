from __future__ import annotations

from gateway.core.approvals import Approval
from gateway.pentagi.mutations import (
    CREATE_FLOW_MUTATION,
    DELETE_FLOW_MUTATION,
    FINISH_FLOW_MUTATION,
    PUT_USER_INPUT_MUTATION,
    RENAME_FLOW_MUTATION,
    STOP_FLOW_MUTATION,
)
from gateway.telegram.formatter import (
    approval_markup,
    format_approval,
    format_flow_list,
    format_providers,
    main_menu_markup,
    provider_label,
)
from gateway.telegram.handlers import CommandHandlers
from tests.helpers import FakeContext, FakeUpdate


def _callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_mutation_constants_match_pentagi_v2_schema_names_args():
    assert "createFlow(modelProvider: $modelProvider, input: $input)" in CREATE_FLOW_MUTATION
    assert "CreateFlowInput" not in CREATE_FLOW_MUTATION
    assert "putUserInput(flowId: $flowId, input: $input)" in PUT_USER_INPUT_MUTATION
    assert "stopFlow(flowId: $flowId)" in STOP_FLOW_MUTATION
    assert "finishFlow(flowId: $flowId)" in FINISH_FLOW_MUTATION
    assert "deleteFlow(flowId: $flowId)" in DELETE_FLOW_MUTATION
    assert "renameFlow(flowId: $flowId, title: $title)" in RENAME_FLOW_MUTATION
    assert "$name" not in RENAME_FLOW_MUTATION
    for mutation in (STOP_FLOW_MUTATION, FINISH_FLOW_MUTATION, DELETE_FLOW_MUTATION):
        assert " id " not in mutation
        assert "status" not in mutation


def test_provider_label_and_flow_list_do_not_render_raw_provider_dict():
    provider = {"name": "openai-compatible", "type": "custom"}
    assert provider_label(provider) == "openai-compatible (custom)"
    rendered = format_flow_list([{"id": "123", "name": "demo", "status": "ok", "provider": provider}])
    assert "{'name'" not in rendered
    assert "openai-compatible (custom)" in rendered
    providers = format_providers([provider])
    assert "model?" not in providers
    assert "status?" not in providers
    assert "openai-compatible (custom)" in providers


def test_main_menu_contains_required_callbacks_and_stop_is_local_only():
    callbacks = set(_callbacks(main_menu_markup()))
    assert {
        "ui:list_flows",
        "ui:providers",
        "ui:active_status",
        "ui:summary",
        "ui:findings",
        "ui:logs",
        "ui:terminal",
        "ui:stop_local",
        "ui:help",
    }.issubset(callbacks)
    assert "stop_flow" not in callbacks


def test_confirm_delete_text_consistency():
    approval = Approval(
        approval_id="a1",
        code="123456",
        user_id=1,
        chat_id=10,
        action="delete_flow",
        risk="CRITICAL",
        payload={"flow_id": "123"},
        payload_hash="hash",
        status="pending",
        confirm_delete=True,
        created_at=0,
        expires_at=999,
    )
    text = format_approval(approval)
    assert "/confirm_delete <code>" in text
    assert "/confirm-delete" not in text
    assert "approval:confirm_delete:123456" in _callbacks(approval_markup(approval))


class SpyDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def handle_text(self, update, ctx, text):
        self.calls.append(("text", text))

    async def handle_command_action(self, update, ctx, action, payload=None, risk="LOW"):
        self.calls.append(("action", action, payload, risk))

    async def confirm(self, update, code, delete=False):
        self.calls.append(("confirm", code, delete))

    async def deny(self, update, code):
        self.calls.append(("deny", code))


async def test_callback_routing_goes_through_dispatcher_for_ui_flow_and_approval():
    spy = SpyDispatcher()
    handlers = CommandHandlers(client=None, dispatcher=spy)
    await handlers.callback(FakeUpdate(callback_data="ui:summary"), FakeContext())
    await handlers.callback(FakeUpdate(callback_data="flow:logs:123"), FakeContext())
    await handlers.callback(FakeUpdate(callback_data="approval:confirm_delete:654321"), FakeContext())
    await handlers.callback(FakeUpdate(callback_data="approval:deny:111111"), FakeContext())
    assert spy.calls[0][0:2] == ("action", "get_flow_summary")
    assert spy.calls[1][0:3] == ("action", "get_logs", {"flow_id": "123"})
    assert spy.calls[2] == ("confirm", "654321", True)
    assert spy.calls[3] == ("deny", "111111")
