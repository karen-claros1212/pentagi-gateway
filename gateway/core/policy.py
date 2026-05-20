"""Central safety policy for Gateway actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .auth import AuthContext, Role

READ_ONLY_BLOCK_MESSAGE = (
    "Bloqueado: Gateway está en READ_ONLY. Esa acción requiere ASSISTED_EXECUTION y aprobación."
)


class GatewayMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    REPORT_ONLY = "REPORT_ONLY"
    ASSISTED_EXECUTION = "ASSISTED_EXECUTION"
    LOCKED = "LOCKED"


class Risk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


READ_ACTIONS = {
    "list_providers",
    "list_flows",
    "get_flow",
    "get_tasks",
    "get_logs",
    "get_terminal",
    "bind_flow",
    "unbind_flow",
    "watch_flow",
    "unwatch_flow",
    "get_flow_status",
    "get_flow_summary",
    "get_recent_findings",
    "help",
    "stop_local",
    "unknown",
}
MUTATION_ACTIONS = {
    "create_flow",
    "put_user_input",
    "stop_flow",
    "finish_flow",
    "rename_flow",
    "delete_flow",
}
REPORT_ACTIONS = {"get_flow_summary", "get_recent_findings", "get_logs", "get_terminal", "help"}


@dataclass
class ActionDecision:
    allowed: bool
    requires_approval: bool = False
    blocked: bool = False
    message: str = ""
    risk: Risk = Risk.LOW
    action: str = "unknown"
    confirm_delete_required: bool = False


@dataclass
class PolicyConfig:
    mode: GatewayMode = GatewayMode.READ_ONLY
    delete_flow_enabled: bool = False


class PolicyEngine:
    """Authoritative policy. LLM/Telegram/client cannot bypass this."""

    def __init__(self, mode: str = "READ_ONLY", delete_flow_enabled: bool = False) -> None:
        self.mode = GatewayMode(mode.upper())
        self.delete_flow_enabled = delete_flow_enabled

    def evaluate(
        self,
        action: str,
        risk: Risk | str,
        auth: AuthContext,
        payload: dict[str, Any] | None = None,
    ) -> ActionDecision:
        del payload
        risk_value = risk if isinstance(risk, Risk) else Risk(str(risk).upper())
        if self.mode == GatewayMode.LOCKED:
            return ActionDecision(False, blocked=True, message="Bloqueado: Gateway está en LOCKED.", risk=risk_value, action=action)

        if action in READ_ACTIONS:
            if self.mode == GatewayMode.REPORT_ONLY and action not in READ_ACTIONS | REPORT_ACTIONS:
                return ActionDecision(False, blocked=True, message="Bloqueado: REPORT_ONLY solo permite lectura/reportes.", risk=risk_value, action=action)
            return ActionDecision(True, risk=risk_value, action=action)

        if action not in MUTATION_ACTIONS:
            return ActionDecision(False, blocked=True, message="No entendí la acción; necesito aclaración.", risk=Risk.LOW, action="unknown")

        if self.mode == GatewayMode.READ_ONLY:
            return ActionDecision(False, blocked=True, message=READ_ONLY_BLOCK_MESSAGE, risk=risk_value, action=action)
        if self.mode == GatewayMode.REPORT_ONLY:
            return ActionDecision(False, blocked=True, message="Bloqueado: Gateway está en REPORT_ONLY. Solo lectura/reportes.", risk=risk_value, action=action)
        if self.mode != GatewayMode.ASSISTED_EXECUTION:
            return ActionDecision(False, blocked=True, message="Bloqueado por modo de Gateway.", risk=risk_value, action=action)

        if action == "delete_flow":
            if auth.role != Role.ADMIN:
                return ActionDecision(False, blocked=True, message="Bloqueado: deleteFlow requiere rol admin.", risk=Risk.CRITICAL, action=action)
            if not self.delete_flow_enabled:
                return ActionDecision(False, blocked=True, message="Bloqueado: deleteFlow está deshabilitado por defecto.", risk=Risk.CRITICAL, action=action)
            return ActionDecision(False, requires_approval=True, risk=Risk.CRITICAL, action=action, confirm_delete_required=True)

        return ActionDecision(False, requires_approval=True, risk=risk_value, action=action)
