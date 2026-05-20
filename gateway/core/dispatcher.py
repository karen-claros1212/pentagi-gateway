"""Central governance dispatcher with UI State Machine."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..llm import Brain, Intent, IntentDecision
from ..llm.brain import BrainContext
from ..pentagi.client import PentagiClient
from ..security.rate_limiter import RateLimiter
from ..telegram.formatter import (
    active_flow_running_screen,
    assistant_screen,
    error_screen,
    flow_finished_screen,
    flow_waiting_screen,
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
    home_screen,
    new_flow_draft_screen,
    provider_select_screen,
    template_select_screen,
)
from .approvals import ApprovalStore
from .auth import AuthContext, AuthProvider
from .policy import PolicyEngine, READ_ONLY_BLOCK_MESSAGE, Risk
from .session import SessionStore, TelegramSession

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
    Intent.SET_PROVIDER: "set_provider",
    Intent.APPLY_TEMPLATE: "apply_template",
    Intent.SUBMIT_DRAFT: "submit_draft",
    Intent.STOP_FLOW: "stop_flow",
    Intent.VIEW_TERMINAL: "view_terminal",
    Intent.VIEW_ASSISTANT: "view_assistant",
    Intent.SEND_ASSISTANT_MESSAGE: "send_assistant_message",
    Intent.HELP_UI: "help_ui",
    Intent.HELP: "help",
    Intent.UNKNOWN: "unknown",
}

# UI actions that are pure navigation (no mutation)
NAV_UI_ACTIONS = {
    "set_provider",
    "apply_template",
    "submit_draft",  # creates mutation but goes through policy in _show_screen
    "view_terminal",
    "view_assistant",
    "send_assistant_message",
    "help_ui",
    "stop_flow",  # mutation but first shows confirmation
}


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
        """Backward-compatible command middleware."""
        identity = await self._prepare(update, action)
        if identity is None:
            return
        user_id, chat_id, _auth_ctx = identity
        await self._store.audit(user_id, chat_id, action, risk=risk, allowed=True)
        await handler(update, context)

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        identity = await self._prepare(update, "natural_language")
        if identity is None:
            return
        user_id, chat_id, auth_ctx = identity
        session = await self._store.ensure_session(chat_id, user_id, auth_ctx.role.value)

        # Step 1: If there's an active flow, take a snapshot
        if session.active_flow_id and self._client:
            await self._take_snapshot(session)

        # Step 1b: If flow is waiting, route non-command text as user input
        if session.active_flow_status == "waiting" and not text.startswith("/"):
            await self._route(update, auth_ctx, "put_user_input", "HIGH", {"input": text, "flow_id": session.active_flow_id})
            return

        # Step 2: Build rich context and classify
        ctx = await self._build_brain_context(session)
        decision = await self._brain.classify(text, active_flow_id=session.active_flow_id, context=ctx)

        # Step 3: Route by screen state first, then by intent
        await self._route_by_screen(update, auth_ctx, session, text, decision)

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
        session = await self._store.ensure_session(auth_ctx.chat_id, auth_ctx.user_id, auth_ctx.role.value)

        # For navigation UI actions, route to screen
        if action in NAV_UI_ACTIONS:
            decision = IntentDecision(
                intent=_intent_for_action(action),
                risk=risk,
                requires_confirmation=False,
                action=action,
                parameters=payload or {},
            )
            await self._route_nav_action(update, auth_ctx, session, action, decision, payload or {})
            return

        # For commands, take snapshot if there's an active flow
        if session.active_flow_id and self._client:
            await self._take_snapshot(session)

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
            await _reply(update, result.message)
            return
        policy = self._policy().evaluate(result.approval.action, result.approval.risk, auth_ctx, result.approval.payload)
        if policy.blocked or policy.requires_approval is False and not policy.allowed:
            await self._store.audit(user_id, chat_id, "mutation_blocked", risk=result.approval.risk, allowed=False, reason=policy.message)
            await _reply(update, policy.message or READ_ONLY_BLOCK_MESSAGE)
            return
        if result.approval.action == "delete_flow" and not delete:
            await _reply(update, "deleteFlow requiere /confirm_delete <code>.")
            return
        mutation_result = await self._execute_mutation(result.approval.action, result.approval.payload)
        await self._store.audit(user_id, chat_id, "mutation_executed", risk=result.approval.risk, allowed=True, reason=result.approval.action)
        await _reply(update, format_mutation_result(result.approval.action, mutation_result))

    async def deny(self, update: Update, code: str) -> None:
        identity = await self._prepare(update, "deny")
        if identity is None:
            return
        user_id, chat_id, _auth_ctx = identity
        result = await self._approvals.deny(code, user_id, chat_id)
        await _reply(update, result.message)

    async def _take_snapshot(self, session: TelegramSession) -> None:
        """Snapshot current PentAGI state and update session fields."""
        if not self._client or not session.active_flow_id:
            return
        try:
            flow = await self._client.get_flow(session.active_flow_id)
            if flow:
                session.active_flow_status = flow.get("status")
                session.selected_provider = provider_name(flow.get("provider"))
            tasks = await self._client.get_tasks(session.active_flow_id)
            tasks_count = len(tasks)
            logs = await self._client.get_message_logs(session.active_flow_id, limit=5)
            assistants = await self._try_get_assistants()
            session.last_snapshot_at = time.time()
            await self._store.upsert_session(session)
            # Store snapshot data back for context building
            session.assistants = assistants
            session.tasks_count = tasks_count
            session.recent_logs = logs
        except Exception as exc:
            logger.warning("Snapshot failed for flow %s: %s", session.active_flow_id, exc)

    async def _try_get_assistants(self) -> list[dict[str, Any]]:
        """Try to fetch assistants list, return empty on failure."""
        if not self._client:
            return []
        try:
            return await self._client.list_providers()
        except Exception:
            return []

    async def _build_brain_context(self, session: TelegramSession) -> BrainContext:
        """Build a BrainContext from session and available data."""
        providers = []
        if self._client:
            try:
                providers = await self._client.list_providers() or []
            except Exception:
                providers = []
        return BrainContext(
            flow_status=session.active_flow_status,
            providers=providers,
            assistants=getattr(session, "assistants", []),
            tasks_count=getattr(session, "tasks_count", 0),
            recent_logs=getattr(session, "recent_logs", []),
            gateway_mode=self._settings.gateway_mode,
            last_screen=session.last_screen,
            draft_message=session.draft_message,
            selected_provider=session.selected_provider,
            selected_assistant_id=session.selected_assistant_id,
            active_flow_id=session.active_flow_id,
        )

    async def _route_by_screen(
        self,
        update: Update,
        auth_ctx: AuthContext,
        session: TelegramSession,
        text: str,
        decision: IntentDecision,
    ) -> None:
        action = INTENT_TO_ACTION.get(decision.intent, "unknown")
        payload = dict(decision.parameters)

        # Enrich payload with flow info
        flow_id = decision.flow_ref or session.active_flow_id
        if flow_id and "flow_id" not in payload:
            payload["flow_id"] = flow_id
        # Include user_response for unknown/help intents
        if action in {"help", "help_ui", "unknown"} and decision.user_response:
            payload["message"] = decision.user_response

        # Check if text is input for draft
        if session.last_screen == "new_flow_draft" and session.draft_message is not None and not text.startswith("/"):
            action = "submit_draft"
            decision.intent = Intent.SUBMIT_DRAFT
            decision.action = "submit_draft"
            session.draft_message = text
            await self._store.upsert_session(session)
            await self._route_nav_action(update, auth_ctx, session, action, decision, payload)
            return

        # Check if text is for assistant
        if session.last_screen == "assistant" and not text.startswith("/"):
            action = "send_assistant_message"
            decision.intent = Intent.SEND_ASSISTANT_MESSAGE
            decision.action = "send_assistant_message"
            payload = {"message": text}
            await self._route_nav_action(update, auth_ctx, session, action, decision, payload)
            return

        # If it's a navigation UI action, show the screen
        if action in NAV_UI_ACTIONS:
            await self._route_nav_action(update, auth_ctx, session, action, decision, payload)
            return

        # Otherwise, route through policy pipeline
        await self._route(update, auth_ctx, action, decision.risk, payload)

    async def _route_nav_action(
        self,
        update: Update,
        auth_ctx: AuthContext,
        session: TelegramSession,
        action: str,
        decision: IntentDecision,
        payload: dict[str, Any],
    ) -> None:
        """Handle navigation UI actions."""
        try:
            if action == "submit_draft":
                await self._handle_submit_draft(update, auth_ctx, session, payload)
                return

            if action == "stop_flow":
                flow_id = payload.get("flow_id") or session.active_flow_id
                # Route through mutation policy for payload validation
                await self._route(
                    update, auth_ctx, "stop_flow", "HIGH",
                    {"flow_id": flow_id},
                )
                return

            if action == "set_provider":
                provider = payload.get("provider") or decision.parameters.get("provider") or ""
                if provider:
                    session.selected_provider = provider
                    session.last_screen = "home"
                    await self._store.upsert_session(session)
                providers_raw = await self._fetch_providers()
                text, markup = provider_select_screen(providers_raw, provider)
                await _reply(update, text, markup)
                return

            if action == "apply_template":
                tid = payload.get("template_id") or decision.parameters.get("template_id") or ""
                if tid:
                    session.draft_template_id = tid
                    session.last_screen = "home"
                    await self._store.upsert_session(session)
                text, markup = template_select_screen([], tid)
                await _reply(update, text, markup)
                return

            if action == "view_terminal":
                if not session.active_flow_id:
                    await _reply(update, NO_ACTIVE_FLOW_TEXT)
                    return
                logs_raw = await self._fetch_terminal_logs(session.active_flow_id)
                result = format_terminal_logs(logs_raw)
                await _reply(update, result)
                return

            if action == "view_assistant":
                assistants = await self._try_get_assistants()
                text, markup = assistant_screen(assistants, [])
                session.last_screen = "assistant"
                await self._store.upsert_session(session)
                await _reply(update, text, markup)
                return

            if action == "send_assistant_message":
                msg = payload.get("message") or ""
                await _reply(update, f"Assistant mensaje: {msg[:200]}\n(Integración callAssistant pendiente)")
                return

            if action == "help_ui":
                screen = decision.parameters.get("screen") or session.last_screen
                helps = {
                    "home": "Pantalla principal. Usa los botones para navegar.",
                    "new_flow_draft": "Escribe tu objetivo para crear un nuevo flow. Luego selecciona provider y template.",
                    "assistant": "Modo asistente conversacional. Escribe tu mensaje.",
                }
                msg = helps.get(screen, f"Ayuda contextual para pantalla {screen}.")
                await _reply(update, f"💡 {msg}")
                return

            # Fallback: show home screen
            await self._show_home(update, session)

        except Exception as exc:
            logger.error("Screen error: %s", exc)
            await _reply(update, error_screen(str(exc)))

    async def _handle_submit_draft(
        self,
        update: Update,
        auth_ctx: AuthContext,
        session: TelegramSession,
        payload: dict[str, Any],
    ) -> None:
        """Handle draft submission."""
        prompt = payload.get("prompt") or session.draft_message or ""
        if not prompt:
            session.last_screen = "new_flow_draft"
            await self._store.upsert_session(session)
            text, _markup = new_flow_draft_screen(session, [], [])
            await _reply(update, text)
            return

        if self._settings.gateway_mode == "READ_ONLY":
            msg = READ_ONLY_BLOCK_MESSAGE + "\n\nPreview: objetivo: " + str(prompt)[:200]
            await _reply(update, msg)
            return

        # Route through mutation policy
        await self._route(
            update, auth_ctx, "create_flow", "HIGH",
            {"input": {"prompt": prompt}},
        )

    async def _show_home(self, update: Update, session: TelegramSession) -> None:
        providers_raw = await self._fetch_providers()
        text, markup = home_screen(session, providers_raw, [])
        session.last_screen = "home"
        session.draft_message = None
        await self._store.upsert_session(session)
        await _reply(update, text, markup)

    async def _fetch_providers(self) -> list[dict[str, Any]]:
        if not self._client:
            return []
        try:
            return await self._client.list_providers() or await self._client.get_settings_providers() or []
        except Exception:
            return []

    async def _fetch_terminal_logs(self, flow_id: str) -> list[dict[str, Any]]:
        if not self._client:
            return []
        try:
            return await self._client.get_terminal_logs(flow_id, limit=30) or []
        except Exception:
            return []

    async def _reply_with_screen(
        self,
        update: Update,
        session: TelegramSession,
        action: str,
        text: str,
    ) -> None:
        """Reply and possibly update screen based on action."""
        session.last_screen = self._screen_for_action(action)
        await self._store.upsert_session(session)
        await _reply(update, text)

    async def _route(
        self,
        update: Update,
        auth_ctx: AuthContext,
        action: str,
        risk: str,
        payload: dict[str, Any],
    ) -> None:
        policy = self._policy().evaluate(action, Risk(risk.upper()), auth_ctx, payload)
        if policy.blocked:
            await self._store.audit(
                auth_ctx.user_id, auth_ctx.chat_id,
                "mutation_blocked" if action in self._mutation_actions() else action,
                risk=policy.risk.value, allowed=False, reason=policy.message,
            )
            await _reply(update, policy.message)
            return
        if policy.requires_approval:
            approval = await self._approvals.create(
                auth_ctx.user_id, auth_ctx.chat_id,
                action, policy.risk.value, payload,
                confirm_delete=policy.confirm_delete_required,
            )
            await _reply(update, format_approval(approval))
            return
        result = await self._execute_read(action, auth_ctx, payload)
        session = await self._store.get_session(auth_ctx.chat_id, auth_ctx.user_id)
        if session:
            await self._reply_with_screen(update, session, action, result)
        else:
            await _reply(update, result)

    async def _execute_read(self, action: str, auth_ctx: AuthContext, payload: dict[str, Any]) -> str:
        if self._client is None:
            return "Cliente PentAGI no configurado."
        flow_id = payload.get("flow_id")
        if action == "help" or action == "unknown":
            return payload.get("message") or "Puedo listar flows, abrir/bind flow, resumir, revisar hallazgos y crear aprobaciones."
        if action == "list_providers":
            providers = await self._client.list_providers() or await self._client.get_settings_providers()
            return format_providers(providers)
        if action == "list_flows":
            return format_flow_list(await self._client.list_flows())
        if action == "bind_flow" and flow_id:
            await self._store.bind_flow(auth_ctx.chat_id, auth_ctx.user_id, flow_id)
            flow = await self._client.get_flow(flow_id)
            return "✅ Flow activo vinculado.\n" + format_flow_detail(flow)
        if action == "unbind_flow":
            session = await self._store.ensure_session(auth_ctx.chat_id, auth_ctx.user_id, auth_ctx.role.value)
            session.active_flow_id = None
            session.active_flow_status = None
            await self._store.upsert_session(session)
            return "✅ Flow activo eliminado."
        if not flow_id:
            return "Necesito un flow activo o flow_id."
        if action == "get_flow":
            return format_flow_detail(await self._client.get_flow(flow_id))
        if action == "get_tasks":
            return format_tasks(await self._client.get_tasks(flow_id))
        if action == "get_logs":
            return format_logs(await self._client.get_message_logs(flow_id, limit=20))
        if action == "get_terminal":
            return format_terminal_logs(await self._client.get_terminal_logs(flow_id, limit=30))
        if action in {"get_flow_status", "get_flow_summary"}:
            flow = await self._client.get_flow(flow_id)
            tasks = await self._client.get_tasks(flow_id)
            logs = await self._client.get_message_logs(flow_id, limit=10)
            return format_summary(flow, tasks, logs)
        if action == "get_recent_findings":
            return format_findings(await self._client.get_tasks(flow_id), await self._client.get_message_logs(flow_id, limit=20))
        if action == "watch_flow":
            return "Watch registrado localmente; subscriptions están controladas por PENTAGI_SUBSCRIPTIONS_ENABLED."
        if action == "unwatch_flow":
            return "Watch eliminado localmente."
        return "Acción de lectura no soportada."

    async def _execute_mutation(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            return {"error": "Cliente PentAGI no configurado"}
        if action == "create_flow":
            return await self._client.create_flow(
                payload.get("input", payload),
                model_provider=self._settings.pentagi_default_provider,
            )
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

    def _payload_for(self, action: str, decision: Any, text: str, active_flow_id: str | None) -> dict[str, Any]:
        flow_id = decision.flow_ref or active_flow_id
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

    def _mutation_actions(self) -> set[str]:
        return {
            "create_flow", "put_user_input", "stop_flow",
            "finish_flow", "rename_flow", "delete_flow",
        }

    def _screen_for_action(self, action: str) -> str:
        mapping = {
            "list_flows": "flows",
            "list_providers": "providers",
            "get_flow": "flow_detail",
            "help": "home",
            "unknown": "home",
        }
        return mapping.get(action, "home")

    async def _prepare(self, update: Update, action: str) -> tuple[int, int, AuthContext] | None:
        user_id = update.effective_user.id if update.effective_user else 0
        chat_id = update.effective_chat.id if update.effective_chat else 0
        if not self._auth.is_authorized(user_id, chat_id):
            logger.warning("Unauthorized attempt uid=%d cid=%d action=%s", user_id, chat_id, action)
            await _reply(update, "⛔ Unauthorized.")
            return None
        if not self._rate.is_allowed(str(user_id)):
            await _reply(update, "⏳ Rate limited. Try again in a moment.")
            return None
        auth_ctx = self._auth.build_context(user_id, chat_id)
        await self._store.ensure_session(chat_id, user_id, auth_ctx.role.value)
        return user_id, chat_id, auth_ctx


def provider_name(provider: dict[str, Any] | str | None) -> str:
    if not provider:
        return ""
    if isinstance(provider, dict):
        return provider.get("name") or provider.get("provider") or ""
    return str(provider)


def _intent_for_action(action: str) -> Intent:
    """Reverse lookup: action string -> Intent enum."""
    reverse = {v: k for k, v in INTENT_TO_ACTION.items()}
    return reverse.get(action, Intent.HELP_UI)


NO_ACTIVE_FLOW_TEXT = "No tengo un flow activo seleccionado. Puedo mostrarte los flows disponibles."


async def _reply(update: Update, text: str, markup: Any = None) -> None:
    target = update.callback_query.message if getattr(update, "callback_query", None) else update.message
    kwargs = {"reply_markup": markup} if markup else {}
    await target.reply_text(text, **kwargs)
