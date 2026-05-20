"""Central governance dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..llm import Brain, Intent
from ..pentagi.client import PentagiClient
from ..security import redact
from ..security.rate_limiter import RateLimiter
from ..telegram.formatter import (
    NO_ACTIVE_FLOW_TEXT,
    SAFE_ERROR_TEXT,
    approval_markup,
    error_markup,
    flow_actions_markup,
    flows_markup,
    format_approval,
    format_findings,
    format_flow_detail,
    format_flow_list,
    format_logs,
    format_mutation_result,
    format_providers,
    format_summary,
    format_tasks,
    format_terminal_logs,
    main_menu_markup,
    no_active_flow_markup,
)
from .approvals import ApprovalStore
from .auth import AuthContext, AuthProvider
from .policy import PolicyEngine, READ_ONLY_BLOCK_MESSAGE, Risk
from .session import SessionStore

logger = logging.getLogger(__name__)

INTENT_TO_ACTION = {
    Intent.LIST_PROVIDERS: "list_providers",
    Intent.LIST_FLOWS: "list_flows",
    Intent.GET_FLOW: "get_flow",
    Intent.GET_TASKS: "get_tasks",
    Intent.GET_LOGS: "get_logs",
    Intent.GET_TERMINAL: "get_terminal",
    Intent.BIND_FLOW: "bind_flow",
    Intent.UNBIND_FLOW: "unbind_flow",
    Intent.WATCH_FLOW: "watch_flow",
    Intent.UNWATCH_FLOW: "unwatch_flow",
    Intent.GET_FLOW_STATUS: "get_flow_status",
    Intent.GET_FLOW_SUMMARY: "get_flow_summary",
    Intent.GET_RECENT_FINDINGS: "get_recent_findings",
    Intent.CREATE_FLOW_REQUEST: "create_flow",
    Intent.SEND_USER_INPUT_REQUEST: "put_user_input",
    Intent.STOP_FLOW_REQUEST: "stop_flow",
    Intent.FINISH_FLOW_REQUEST: "finish_flow",
    Intent.RENAME_FLOW_REQUEST: "rename_flow",
    Intent.DELETE_FLOW_REQUEST: "delete_flow",
    Intent.HELP: "help",
    Intent.UNKNOWN: "unknown",
}
FLOW_DEPENDENT_READS = {
    "get_flow",
    "get_tasks",
    "get_logs",
    "get_terminal",
    "get_flow_status",
    "get_flow_summary",
    "get_recent_findings",
    "watch_flow",
    "unwatch_flow",
}
MUTATION_ACTIONS = {"put_user_input", "stop_flow", "finish_flow", "rename_flow", "delete_flow", "create_flow"}


class Dispatcher:
    """Auth -> rate-limit -> Brain/NL -> policy -> approval/read/mutation."""

    def __init__(
        self,
        auth: AuthProvider,
        store: SessionStore,
        rate_limiter: RateLimiter | None = None,
        settings: Settings | None = None,
        client: PentagiClient | None = None,
        brain: Brain | None = None,
    ) -> None:
        self._auth = auth
        self._store = store
        self._rate = rate_limiter or RateLimiter()
        self._settings = settings or Settings()
        self._client = client
        self._brain = brain or Brain(
            enabled=self._settings.llm_enabled,
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
            model=self._settings.llm_model,
        )
        self._approvals = ApprovalStore(store, ttl_seconds=self._settings.approval_ttl_seconds)

    async def dispatch(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]],
        risk: str = "low",
    ) -> None:
        identity = await self._prepare(update, action)
        if identity is None:
            return
        user_id, chat_id, _auth_ctx = identity
        await self._store.audit(user_id, chat_id, action, risk=risk, allowed=True)
        await handler(update, context)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        del context
        identity = await self._prepare(update, "natural_language")
        if identity is None:
            return
        user_id, chat_id, auth_ctx = identity
        session = await self._store.ensure_session(chat_id, user_id, auth_ctx.role.value)
        decision = await self._brain.classify(text, active_flow_id=session.active_flow_id)
        action = INTENT_TO_ACTION.get(decision.intent, "unknown")
        payload = self._payload_for(action, decision, text, session.active_flow_id)
        await self._route(update, auth_ctx, action, decision.risk, payload)

    async def handle_command_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        payload: dict[str, Any] | None = None,
        risk: str = "LOW",
    ) -> None:
        del context
        identity = await self._prepare(update, action)
        if identity is None:
            return
        _user_id, _chat_id, auth_ctx = identity
        await self._route(update, auth_ctx, action, risk, payload or {})

    async def confirm(self, update: Update, code: str, delete: bool = False) -> None:
        identity = await self._prepare(update, "confirm_delete" if delete else "confirm")
        if identity is None:
            return
        user_id, chat_id, auth_ctx = identity
        result = await self._approvals.confirm(
            code,
            user_id,
            chat_id,
            require_delete=delete,
            allow_delete=self._settings.delete_flow_enabled,
        )
        if not result.ok or result.approval is None:
            await _reply(update, result.message, reply_markup=error_markup())
            return
        policy = self._policy().evaluate(
            result.approval.action,
            result.approval.risk,
            auth_ctx,
            result.approval.payload,
        )
        if policy.blocked or policy.requires_approval is False and not policy.allowed:
            await self._store.audit(
                user_id,
                chat_id,
                "mutation_blocked",
                risk=result.approval.risk,
                allowed=False,
                reason=policy.message,
            )
            await _reply(update, policy.message or READ_ONLY_BLOCK_MESSAGE, reply_markup=error_markup())
            return
        if result.approval.action == "delete_flow" and not delete:
            await _reply(update, "deleteFlow requiere /confirm-delete <code>.", reply_markup=error_markup())
            return
        try:
            mutation_result = await self._execute_mutation(result.approval.action, result.approval.payload)
        except Exception as exc:  # noqa: BLE001 - user gets safe error only
            await self._store.audit(
                user_id,
                chat_id,
                "mutation_blocked",
                risk=result.approval.risk,
                allowed=False,
                reason=redact(str(exc))[:200],
            )
            logger.exception("safe mutation execution error")
            await _reply(update, SAFE_ERROR_TEXT, reply_markup=error_markup())
            return
        await self._store.audit(
            user_id,
            chat_id,
            "mutation_executed",
            risk=result.approval.risk,
            allowed=True,
            reason=result.approval.action,
        )
        await _reply(update, format_mutation_result(result.approval.action, mutation_result), reply_markup=main_menu_markup())

    async def deny(self, update: Update, code: str) -> None:
        identity = await self._prepare(update, "deny")
        if identity is None:
            return
        user_id, chat_id, _auth_ctx = identity
        result = await self._approvals.deny(code, user_id, chat_id)
        await _reply(update, result.message, reply_markup=main_menu_markup())

    async def _route(
        self,
        update: Update,
        auth_ctx: AuthContext,
        action: str,
        risk: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            policy = self._policy().evaluate(action, Risk(risk.upper()), auth_ctx, payload)
            if policy.blocked:
                audit_action = "mutation_blocked" if action in MUTATION_ACTIONS else action
                await self._store.audit(
                    auth_ctx.user_id,
                    auth_ctx.chat_id,
                    audit_action,
                    risk=policy.risk.value,
                    allowed=False,
                    reason=policy.message,
                )
                await _reply(update, policy.message, reply_markup=error_markup())
                return
            if policy.requires_approval:
                approval = await self._approvals.create(
                    auth_ctx.user_id,
                    auth_ctx.chat_id,
                    action,
                    policy.risk.value,
                    payload,
                    confirm_delete=policy.confirm_delete_required,
                )
                await _reply(update, format_approval(approval), reply_markup=approval_markup(approval))
                return
            result, markup = await self._execute_read(action, auth_ctx, payload)
            await self._store.audit(
                auth_ctx.user_id,
                auth_ctx.chat_id,
                action,
                risk=policy.risk.value,
                allowed=True,
            )
            await _reply(update, result, reply_markup=markup)
        except Exception as exc:  # noqa: BLE001 - user gets safe error only
            logger.exception("safe dispatcher error")
            await self._store.audit(
                auth_ctx.user_id,
                auth_ctx.chat_id,
                action,
                risk=risk,
                allowed=False,
                reason=redact(str(exc))[:200],
            )
            await _reply(update, SAFE_ERROR_TEXT, reply_markup=error_markup())

    async def _execute_read(
        self,
        action: str,
        auth_ctx: AuthContext,
        payload: dict[str, Any],
    ) -> tuple[str, Any | None]:
        if action == "stop_local":
            session = await self._store.ensure_session(auth_ctx.chat_id, auth_ctx.user_id, auth_ctx.role.value)
            session.active_flow_id = None
            await self._store.upsert_session(session)
            return "Operación local detenida. No se ejecutó ninguna acción en PentAGI.", main_menu_markup()
        if action == "help" or action == "unknown":
            return (
                payload.get("message")
                or "Puedo listar flows, abrir flow <id>, resumir el flow activo o revisar hallazgos.",
                main_menu_markup(),
            )
        if self._client is None:
            return SAFE_ERROR_TEXT, error_markup()
        flow_id = payload.get("flow_id")
        if action == "list_providers":
            providers = await self._client.list_providers() or await self._client.get_settings_providers()
            return format_providers(providers), main_menu_markup()
        if action == "list_flows":
            flows = await self._client.list_flows()
            return format_flow_list(flows), flows_markup(flows)
        if action == "unbind_flow":
            session = await self._store.ensure_session(auth_ctx.chat_id, auth_ctx.user_id, auth_ctx.role.value)
            session.active_flow_id = None
            await self._store.upsert_session(session)
            return "✅ Flow activo eliminado.", main_menu_markup()
        if action in FLOW_DEPENDENT_READS | {"bind_flow"} and not _is_valid_flow_id(flow_id):
            return NO_ACTIVE_FLOW_TEXT, no_active_flow_markup()
        if action == "bind_flow":
            await self._store.bind_flow(auth_ctx.chat_id, auth_ctx.user_id, str(flow_id))
            flow = await self._client.get_flow(str(flow_id))
            return "✅ Flow activo vinculado.\n" + format_flow_detail(flow), flow_actions_markup(str(flow_id))
        if action == "get_flow":
            return format_flow_detail(await self._client.get_flow(str(flow_id))), flow_actions_markup(str(flow_id))
        if action == "get_tasks":
            return format_tasks(await self._client.get_tasks(str(flow_id))), flow_actions_markup(str(flow_id))
        if action == "get_logs":
            return format_logs(await self._client.get_message_logs(str(flow_id), limit=20)), flow_actions_markup(str(flow_id))
        if action == "get_terminal":
            return format_terminal_logs(await self._client.get_terminal_logs(str(flow_id), limit=30)), flow_actions_markup(str(flow_id))
        if action in {"get_flow_status", "get_flow_summary"}:
            flow = await self._client.get_flow(str(flow_id))
            tasks = await self._client.get_tasks(str(flow_id))
            logs = await self._client.get_message_logs(str(flow_id), limit=10)
            return format_summary(flow, tasks, logs), flow_actions_markup(str(flow_id))
        if action == "get_recent_findings":
            tasks = await self._client.get_tasks(str(flow_id))
            logs = await self._client.get_message_logs(str(flow_id), limit=20)
            return format_findings(tasks, logs), flow_actions_markup(str(flow_id))
        if action == "watch_flow":
            return (
                "Watch registrado localmente; subscriptions están controladas por PENTAGI_SUBSCRIPTIONS_ENABLED.",
                flow_actions_markup(str(flow_id)),
            )
        if action == "unwatch_flow":
            return "Watch eliminado localmente.", flow_actions_markup(str(flow_id))
        return "Acción de lectura no soportada.", main_menu_markup()

    async def _execute_mutation(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            return {"error": "Cliente PentAGI no configurado"}
        if action == "create_flow":
            return await self._client.create_flow(payload.get("input", payload))
        if action == "put_user_input":
            return await self._client.put_user_input(payload["flow_id"], payload["input"])
        if action == "stop_flow":
            return await self._client.stop_flow(payload["flow_id"])
        if action == "finish_flow":
            return await self._client.finish_flow(payload["flow_id"])
        if action == "rename_flow":
            return await self._client.rename_flow(payload["flow_id"], payload["name"])
        if action == "delete_flow":
            return await self._client.delete_flow(payload["flow_id"])
        return {"error": "mutation unsupported"}

    def _payload_for(
        self,
        action: str,
        decision: Any,
        text: str,
        active_flow_id: str | None,
    ) -> dict[str, Any]:
        raw_flow_id = decision.flow_ref or active_flow_id
        flow_id = str(raw_flow_id) if raw_flow_id is not None else None
        if not _is_valid_flow_id(flow_id):
            flow_id = None
        if action == "create_flow":
            return {"input": {"prompt": decision.parameters.get("prompt") or text}}
        if action == "put_user_input":
            return {"flow_id": flow_id, "input": decision.parameters.get("input") or text}
        if action in {"stop_flow", "finish_flow", "delete_flow"}:
            return {"flow_id": flow_id}
        if action == "rename_flow":
            return {"flow_id": flow_id, "name": decision.parameters.get("name") or text}
        if action == "unknown":
            return {"message": decision.user_response}
        return {"flow_id": flow_id} if flow_id else {}

    def _policy(self) -> PolicyEngine:
        return PolicyEngine(self._settings.gateway_mode, self._settings.delete_flow_enabled)

    async def _prepare(self, update: Update, action: str) -> tuple[int, int, AuthContext] | None:
        user_id = update.effective_user.id if update.effective_user else 0
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._auth.is_authorized(user_id, chat_id):
            logger.warning("Unauthorized attempt uid=%d cid=%d action=%s", user_id, chat_id, action)
            await _reply(update, "⛔ Unauthorized.", reply_markup=error_markup())
            return None
        if not self._rate.is_allowed(str(user_id)):
            await _reply(update, "⏳ Rate limited. Try again in a moment.", reply_markup=main_menu_markup())
            return None
        auth_ctx = self._auth.build_context(user_id, chat_id)
        await self._store.ensure_session(chat_id, user_id, auth_ctx.role.value)
        return user_id, chat_id, auth_ctx


def _is_valid_flow_id(flow_id: Any) -> bool:
    return isinstance(flow_id, str) and flow_id.isdigit()


async def _reply(update: Update, text: str, reply_markup: Any | None = None) -> None:
    target = update.callback_query.message if getattr(update, "callback_query", None) else update.message
    try:
        await target.reply_text(text, reply_markup=reply_markup)
    except TypeError:
        await target.reply_text(text)
