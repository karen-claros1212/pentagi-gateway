"""Strict JSON intent schemas for natural-language classification."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
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
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


MUTATION_INTENTS = {
    Intent.CREATE_FLOW_REQUEST,
    Intent.SEND_USER_INPUT_REQUEST,
    Intent.STOP_FLOW_REQUEST,
    Intent.FINISH_FLOW_REQUEST,
    Intent.RENAME_FLOW_REQUEST,
    Intent.DELETE_FLOW_REQUEST,
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
