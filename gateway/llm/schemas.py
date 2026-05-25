"""Strict JSON intent schemas for natural-language classification."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    GREETING = "GREETING"
    WHO_ARE_YOU = "WHO_ARE_YOU"
    CAPABILITIES = "CAPABILITIES"
    GATEWAY_STATUS = "GATEWAY_STATUS"
    CONTEXT_HELP = "CONTEXT_HELP"
    GET_STATUS = "GET_STATUS"
    LIST_PROVIDERS = "LIST_PROVIDERS"
    LIST_FLOWS = "LIST_FLOWS"
    GET_FLOW = "GET_FLOW"
    GET_TASKS = "GET_TASKS"
    GET_LOGS = "GET_LOGS"
    GET_TERMINAL = "GET_TERMINAL"
    BIND_FLOW = "BIND_FLOW"
    UNBIND_FLOW = "UNBIND_FLOW"
    WATCH_FLOW = "WATCH_FLOW"
    UNWATCH_FLOW = "UNWATCH_FLOW"
    GET_FLOW_STATUS = "GET_FLOW_STATUS"
    GET_FLOW_SUMMARY = "GET_FLOW_SUMMARY"
    GET_RECENT_FINDINGS = "GET_RECENT_FINDINGS"
    CREATE_FLOW_REQUEST = "CREATE_FLOW_REQUEST"
    SEND_USER_INPUT_REQUEST = "SEND_USER_INPUT_REQUEST"
    STOP_FLOW_REQUEST = "STOP_FLOW_REQUEST"
    FINISH_FLOW_REQUEST = "FINISH_FLOW_REQUEST"
    RENAME_FLOW_REQUEST = "RENAME_FLOW_REQUEST"
    DELETE_FLOW_REQUEST = "DELETE_FLOW_REQUEST"
    SET_PROVIDER = "SET_PROVIDER"
    APPLY_TEMPLATE = "APPLY_TEMPLATE"
    SUBMIT_DRAFT = "SUBMIT_DRAFT"
    STOP_FLOW = "STOP_FLOW"
    VIEW_TERMINAL = "VIEW_TERMINAL"
    VIEW_ASSISTANT = "VIEW_ASSISTANT"
    GET_ASSISTANTS = "GET_ASSISTANTS"
    SEND_ASSISTANT_MESSAGE = "SEND_ASSISTANT_MESSAGE"
    CREATE_ASSISTANT = "CREATE_ASSISTANT"
    CALL_ASSISTANT = "CALL_ASSISTANT"
    STOP_ASSISTANT = "STOP_ASSISTANT"
    DELETE_ASSISTANT = "DELETE_ASSISTANT"
    HELP_UI = "HELP_UI"
    HELP = "HELP"
    SMALLTALK = "SMALLTALK"
    UNKNOWN = "UNKNOWN"
    # Operator identity intents
    OPERATOR_INTRO = "OPERATOR_INTRO"
    OPERATOR_IDENTITY = "OPERATOR_IDENTITY"
    OPERATOR_CAPABILITIES = "OPERATOR_CAPABILITIES"
    CONFIRM_NEW_FLOW = "CONFIRM_NEW_FLOW"


MUTATION_INTENTS = {
    Intent.CREATE_FLOW_REQUEST,
    Intent.SEND_USER_INPUT_REQUEST,
    Intent.STOP_FLOW_REQUEST,
    Intent.FINISH_FLOW_REQUEST,
    Intent.RENAME_FLOW_REQUEST,
    Intent.DELETE_FLOW_REQUEST,
    Intent.CREATE_ASSISTANT,
    Intent.CALL_ASSISTANT,
    Intent.STOP_ASSISTANT,
    Intent.DELETE_ASSISTANT,
    Intent.CONFIRM_NEW_FLOW,
}


class IntentDecision(BaseModel):
    intent: Intent = Intent.UNKNOWN
    risk: str = "LOW"
    requires_confirmation: bool = False
    flow_ref: str | None = None
    action: str | None = None
    user_response: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    def normalized(self) -> IntentDecision:
        if self.intent in MUTATION_INTENTS:
            self.requires_confirmation = True
            risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
            if risk_order.get(self.risk.upper(), 0) < risk_order["HIGH"]:
                self.risk = "HIGH"
        if self.intent == Intent.DELETE_FLOW_REQUEST:
            self.risk = "CRITICAL"
        return self
