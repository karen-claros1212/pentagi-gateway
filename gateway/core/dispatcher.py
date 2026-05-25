"""Central governance dispatcher with UI State Machine."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Coroutine
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..llm import Brain, Intent, IntentDecision
from ..llm.brain import BrainContext
from ..security.rate_limiter import RateLimiter
from ..telegram.formatter import (
    assistant_screen,
    error_screen,
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
from .interfaces import IAuthProvider, IPentagiClient, IRateLimiter, ISessionStore
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
    Intent.CONFIRM_NEW_FLOW: "confirm_new_flow",
    Intent.SET_PROVIDER: "set_provider",
    Intent.APPLY_TEMPLATE: "apply_template",
    Intent.SUBMIT_DRAFT: "submit_draft",
    Intent.STOP_FLOW: "stop_flow",
    Intent.VIEW_TERMINAL: "view_terminal",
    Intent.VIEW_ASSISTANT: "view_assistant",
    Intent.GET_ASSISTANTS: "get_assistants",
    Intent.SEND_ASSISTANT_MESSAGE: "call_assistant",
    Intent.CREATE_ASSISTANT: "create_assistant",
    Intent.CALL_ASSISTANT: "call_assistant",
    Intent.STOP_ASSISTANT: "stop_assistant",
    Intent.DELETE_ASSISTANT: "delete_assistant",
    Intent.HELP_UI: "help_ui",
    Intent.HELP: "help",
    Intent.GREETING: "operator_intro",
    Intent.WHO_ARE_YOU: "operator_identity",
    Intent.CAPABILITIES: "operator_capabilities",
    Intent.OPERATOR_INTRO: "operator_intro",
    Intent.OPERATOR_IDENTITY: "operator_identity",
    Intent.OPERATOR_CAPABILITIES: "operator_capabilities",
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
    "create_assistant",
    "call_assistant",
    "stop_assistant",
    "delete_assistant",
    "help_ui",
    "stop_flow",  # mutation but first shows confirmation
    "new_flow_draft",  # prompts for flow objective text
    "confirm_new_flow",  # creates flow after confirmation
    "select_assistant",  # selects assistant from list
}

# Control commands that bypass assistant mode and go to Gateway
CONTROL_KEYWORDS = {
    "ayuda": Intent.HELP_UI,
    "help": Intent.HELP_UI,
    "tareas": Intent.GET_TASKS,
    "ver tareas": Intent.GET_TASKS,
    "logs": Intent.GET_LOGS,
    "terminal": Intent.VIEW_TERMINAL,
    "asistente": Intent.VIEW_ASSISTANT,
    "cerrar asistente": Intent.VIEW_ASSISTANT,
    "modo agentes": Intent.VIEW_ASSISTANT,
    "proveedor": Intent.LIST_PROVIDERS,
    "flows": Intent.LIST_FLOWS,
    "inicio": Intent.GREETING,
    "home": Intent.GREETING,
    "menú": Intent.GREETING,
    "menu": Intent.GREETING,
    "qué está haciendo": Intent.GET_FLOW_STATUS,
    "que esta haciendo": Intent.GET_FLOW_STATUS,
    "resume": Intent.GET_FLOW_SUMMARY,
    "resumen": Intent.GET_FLOW_SUMMARY,
    "qué encontró": Intent.GET_RECENT_FINDINGS,
    "que encontro": Intent.GET_RECENT_FINDINGS,
    "capacidades": Intent.OPERATOR_CAPABILITIES,
    "capabilities": Intent.OPERATOR_CAPABILITIES,
    "qué puedes hacer": Intent.OPERATOR_CAPABILITIES,
    "que puedes hacer": Intent.OPERATOR_CAPABILITIES,
    "detén": Intent.STOP_FLOW_REQUEST,
    "deten": Intent.STOP_FLOW_REQUEST,
    "stop": Intent.STOP_FLOW_REQUEST,
    "parar": Intent.STOP_FLOW_REQUEST,
    "finaliza": Intent.FINISH_FLOW_REQUEST,
    "finish": Intent.FINISH_FLOW_REQUEST,
    "dile que": Intent.SEND_USER_INPUT_REQUEST,
    "envia": Intent.SEND_USER_INPUT_REQUEST,
    "envía": Intent.SEND_USER_INPUT_REQUEST,
    "continúe": Intent.SEND_USER_INPUT_REQUEST,
    "continue": Intent.SEND_USER_INPUT_REQUEST,
    "quién eres": Intent.OPERATOR_IDENTITY,
    "que eres": Intent.OPERATOR_IDENTITY,
    "identity": Intent.OPERATOR_IDENTITY,
    "intro": Intent.OPERATOR_INTRO,
    "introducción": Intent.OPERATOR_INTRO,
    "introduccion": Intent.OPERATOR_INTRO,
}


class Dispatcher:
    """Auth -> rate-limit -> Brain/NL -> policy -> approval/read/mutation."""

    def __init__(
        self,
        auth: IAuthProvider,
        store: ISessionStore,
        rate_limiter: IRateLimiter | None = None,
        settings: Settings | None = None,
        client: IPentagiClient | None = None,
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
        """State-machine driven text routing by ui_mode. Priority: Draft → Assistant → Flow → Brain."""
        identity = await self._prepare(update, "natural_language")
        if identity is None:
            return
        user_id, chat_id, auth_ctx = identity
        session = await self._store.ensure_session(chat_id, user_id, auth_ctx.role.value)

        # --- PHASE 0: Slash commands (always bypass state machine) ---
        if text.startswith("/"):
            cmd = text[1:].split()[0].lower()
            command_map = {
                "start": ("help", {"message": "Welcome"}),
                "help": ("help", {"message": "Ayuda"}),
                "flows": ("list_flows", {}),
                "providers": ("list_providers", {}),
            }
            if cmd in command_map:
                action, payload = command_map[cmd]
                await self.handle_command_action(update, context, action, payload)
                return

        # --- PHASE 1: FLOW DRAFT — text = objective ---
        if session.ui_mode == "flow_draft":
            session.draft_message = text
            await self._store.upsert_session(session)
            await _reply(update,
                f"✏️ Objetivo guardado: `{text[:200]}`\n\n"
                "¿Confirmar creación del flow?",
                {"inline_keyboard": [
                    [{"text": "✅ Confirmar y crear", "callback_data": "ui:confirm_new_flow"}],
                    [{"text": "❌ Cancelar", "callback_data": "ui:home"}],
                ]})
            return

        # --- PHASE 2: ASSISTANT MODE — text → callAssistant ---
        if session.ui_mode == "assistant" and session.active_flow_id:
            # Check for control commands first (bypass assistant)
            low = text.lower()
            control_intent = None
            for kw, intent in CONTROL_KEYWORDS.items():
                if kw in low:
                    control_intent = intent
                    break

            if control_intent:
                action = INTENT_TO_ACTION.get(control_intent, "help_ui")
                await self._route(update, auth_ctx, action, "LOW", {}, intent=control_intent)
                return

            # If assistant has ID, call it directly (policy allows call_assistant in any mode)
            if session.active_assistant_id:
                await self._route(update, auth_ctx, "call_assistant", "HIGH", {
                    "flow_id": session.active_flow_id,
                    "assistant_id": session.active_assistant_id,
                    "input": text,
                    "use_agents": session.assistant_use_agents,
                })
                return

            # No assistant selected — create one directly
            await self._route_nav_action(update, auth_ctx, session, "view_assistant",
                IntentDecision(intent=Intent.VIEW_ASSISTANT, action="view_assistant",
                    risk="LOW", requires_confirmation=False, parameters={}),
                {})
            return

        # --- PHASE 3: FLOW WAITING — text → putUserInput ---
        if session.ui_mode == "flow_waiting" and session.active_flow_id:
            await self._route(update, auth_ctx, "put_user_input", "HIGH", {
                "flow_id": session.active_flow_id,
                "input": text,
            })
            return

        # --- PHASE 4: FLOW RUNNING — show panel ---
        if session.ui_mode == "flow_running" and session.active_flow_id:
            await _reply(update, "El flow está en marcha. Para interactuar directamente activa Assistant Mode.\n\n"
                "Usa los botones para ver tareas, logs, terminal o detener.",
                {"inline_keyboard": [
                    [{"text": "📋 Tareas", "callback_data": "ui:tasks"}, {"text": "🧾 Logs", "callback_data": "ui:logs"}],
                    [{"text": "🖥 Terminal", "callback_data": "ui:terminal"}, {"text": "⏹ Stop", "callback_data": "ui:stop_flow"}],
                    [{"text": "🔙 Home", "callback_data": "ui:home"}],
                ]})
            return

        # --- PHASE 5: HOME — show menu for greetings ---
        if session.ui_mode == "home":
            low = text.lower().strip()
            home_triggers = {"hola", "hello", "start", "inicio", "home", "menú", "menu", "help"}
            if not text.strip() or any(t in low for t in home_triggers):
                await self._show_home(update, session)
                return

        # --- PHASE 6: READ-ONLY / CLASSIFY — brain as fallback ---
        if session.active_flow_id and self._client:
            await self._take_snapshot(session)
        ctx = await self._build_brain_context(session)
        decision = await self._brain.classify(text, active_flow_id=session.active_flow_id, context=ctx)
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

        await self._route(update, auth_ctx, action, risk, payload or {}, intent=decision.intent if (decision := IntentDecision(intent=_intent_for_action(action))) else None)

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

        # Post-mutation session update for create_assistant
        if result.approval.action == "create_assistant":
            session = await self._store.get_session(chat_id, user_id)
            if session:
                session.assistant_approved = True
                session.assistant_approval_scope = "assistant_session"
                session.assistant_approval_expires = time.time() + 3600  # 1 hour
                assistant_data = mutation_result.get("assistant", {})
                if assistant_data:
                    session.active_assistant_id = assistant_data.get("id") or session.active_assistant_id
                session.last_screen = "assistant"
                await self._store.upsert_session(session)
                # Override result message with approval confirmation
                assistant_title = assistant_data.get("title", "Assistant") if assistant_data else "Assistant"
                await _reply(update,
                    f"✅ Assistant creado y aprobado: {assistant_title}\n"
                    f"Modo: activo. Ahora puedes escribir normalmente para interactuar con el assistant.\n"
                    f"⚙️ Aprobación vigente por 1 hora.")
                return

        # Post-mutation session update for create_flow
        if result.approval.action == "create_flow":
            session = await self._store.get_session(chat_id, user_id)
            if session:
                flow_data = mutation_result.get("createFlow", mutation_result)
                if flow_data:
                    session.active_flow_id = flow_data.get("id") or flow_data.get("flow_id")
                    session.active_flow_status = flow_data.get("status", "waiting")
                    session.ui_mode = "flow_waiting"
                    session.last_screen = "flow_detail"
                    session.draft_message = None
                    await self._store.upsert_session(session)
                await _reply(update, format_mutation_result(result.approval.action, mutation_result))
                return

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
            assistants = await self._try_get_assistants(session.active_flow_id)
            session.last_snapshot_at = time.time()
            await self._store.upsert_session(session)
            # Store snapshot data back for context building
            session.assistants = assistants
            session.tasks_count = tasks_count
            session.recent_logs = logs
        except Exception as exc:
            logger.warning("Snapshot failed for flow %s: %s", session.active_flow_id, exc)

    async def _try_get_assistants(self, flow_id: str | None = None) -> list[dict[str, Any]]:
        if not self._client or not flow_id:
            return []
        try:
            return await self._client.get_assistants(flow_id) or []
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

        # PRECEDENCE: Control commands override assistant mode
        # Even when last_screen == "assistant", control commands should be handled by Gateway first
        if session.last_screen == "assistant" and not text.startswith("/"):
            low = text.lower()
            control_keywords = {
                "ayuda": Intent.HELP_UI,
                "help": Intent.HELP_UI,
                "tareas": Intent.GET_TASKS,
                "ver tareas": Intent.GET_TASKS,
                "logs": Intent.GET_LOGS,
                "terminal": Intent.VIEW_TERMINAL,
                "asistente": Intent.VIEW_ASSISTANT,
                "cerrar asistente": Intent.VIEW_ASSISTANT,
                "modo agentes": Intent.VIEW_ASSISTANT,
                "proveedor": Intent.LIST_PROVIDERS,
                "flows": Intent.LIST_FLOWS,
            }
            is_control = any(kw in low for kw in control_keywords.keys())
            if is_control:
                # Re-classify with control intent
                control_intent = control_keywords.get(
                    next(kw for kw in control_keywords if kw in low),
                    Intent.HELP_UI,
                )
                action = INTENT_TO_ACTION.get(control_intent, "unknown")
                decision = IntentDecision(
                    intent=control_intent,
                    action=action,
                    risk="LOW",
                    requires_confirmation=False,
                    parameters=payload,
                )
                if action in NAV_UI_ACTIONS:
                    await self._route_nav_action(update, auth_ctx, session, action, decision, payload)
                    return
                await self._route(update, auth_ctx, action, decision.risk, payload, intent=decision.intent)
                return

        # Check if text is for assistant (only if not a control command)
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
        await self._route(update, auth_ctx, action, decision.risk, payload, intent=decision.intent)

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
        # Enriquecer payload con flow_id de sesión si no viene explícito
        if not payload.get("flow_id") and session.active_flow_id:
            payload["flow_id"] = session.active_flow_id
        
        try:
            if action == "new_flow_draft":
                session.ui_mode = "flow_draft"
                session.draft_message = None
                session.last_screen = "new_flow_draft"
                await self._store.upsert_session(session)
                await _reply(update,
                    "✏️ *Nuevo Flow*\n\nEscribe tu objetivo para el nuevo flow.",
                    {"inline_keyboard": [[{"text": "🔙 Home", "callback_data": "ui:home"}]]})
                return

            if action == "submit_draft":
                await self._handle_submit_draft(update, auth_ctx, session, payload)
                return

            if action == "stop_flow":
                # Check for active assistant first
                if session.assistant_approved and session.active_assistant_id:
                    await self._route(update, auth_ctx, "stop_assistant", "HIGH", {
                        "flow_id": session.active_flow_id,
                        "assistant_id": session.active_assistant_id,
                    })
                    return
                flow_id = payload.get("flow_id") or session.active_flow_id
                if not isinstance(flow_id, str) or not flow_id.isdigit():
                    await _reply(update, f"Bloqueado: stopFlow requiere un flow_id numérico explícito.")
                    return
                # Route through mutation policy for payload validation
                await self._route(
                    update, auth_ctx, "stop_flow", "HIGH",
                    {"flow_id": flow_id},
                    intent=Intent.STOP_FLOW_REQUEST,
                )
                return

            if action == "confirm_new_flow":
                prompt = session.draft_message or ""
                if not prompt.strip():
                    await _reply(update, "Necesitas escribir un objetivo primero.")
                    return
                if self._settings.gateway_mode == "READ_ONLY":
                    await _reply(update, READ_ONLY_BLOCK_MESSAGE)
                    return
                await self._route(
                    update, auth_ctx, "create_flow", "HIGH",
                    {"input": {"prompt": prompt}},
                    intent=Intent.CREATE_FLOW_REQUEST,
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
                assistants = await self._try_get_assistants(session.active_flow_id)
                if not assistants:
                    # No assistants — create one directly (policy allows create_assistant in any mode)
                    flow_id = payload.get("flow_id") or session.active_flow_id
                    if not flow_id:
                        await _reply(update, "Necesito un flow activo para crear un assistant.")
                        return
                    result = await self._execute_mutation("create_assistant", {
                        "flow_id": flow_id,
                        "model_provider": session.selected_provider or "qwen",
                        "input": session.draft_message or "",
                        "use_agents": session.assistant_use_agents,
                    })
                    assistant_data = result.get("assistant", {})
                    if assistant_data and assistant_data.get("id"):
                        session.active_assistant_id = assistant_data["id"]
                        session.assistant_approved = True
                        session.ui_mode = "assistant"
                        session.last_screen = "assistant"
                        await self._store.upsert_session(session)
                        assistant_title = assistant_data.get("title", "Assistant")
                        await _reply(update,
                            f"✅ Assistant creado: {assistant_title}\n"
                            f"Modo: activo. Escribe para interactuar con el assistant.",
                            {"inline_keyboard": [[{"text": "🔙 Home", "callback_data": "ui:home"}]]})
                    else:
                        await _reply(update, "No se pudo crear el assistant. Intenta de nuevo.")
                    return
                # Show assistant selection screen — DO NOT change ui_mode yet
                text, markup = assistant_screen(assistants, [])
                session.last_screen = "assistant_select"
                await self._store.upsert_session(session)
                await _reply(update, text, markup)
                return

            if action == "select_assistant":
                assistant_id = payload.get("assistant_id") or decision.parameters.get("assistant_id")
                if assistant_id:
                    session.active_assistant_id = assistant_id
                    session.ui_mode = "assistant"
                    session.last_screen = "assistant"
                    # Note: assistant_approved stays False until create_assistant approval
                    await self._store.upsert_session(session)
                await _reply(update,
                    "✅ Assistant seleccionado.\n"
                    "Modo: selección. Para interactuar, crea o aprueba un assistant.",
                    {"inline_keyboard": [
                        [{"text": "⚙️ Solicitar aprobación y crear", "callback_data": "ui:approve_create_assistant"}],
                        [{"text": "🔙 Home", "callback_data": "ui:home"}],
                    ]})
                return

            if action == "create_assistant":
                if self._settings.gateway_mode == "READ_ONLY":
                    return await _reply(update,
                        "Assistant requiere APPROVED_EXECUTION.\n"
                        "¿Solicitar aprobación para crear un assistant?",
                        {"inline_keyboard": [[{"text": "✅ Aprobar y crear", "callback_data": "ui:approve_create_assistant"}, {"text": "❌ Cancelar", "callback_data": "ui:cancel"}]]})
                await self._route(update, auth_ctx, "create_assistant", "HIGH", {
                    "flow_id": session.active_flow_id,
                    "model_provider": session.selected_provider or "qwen",
                    "input": session.draft_message or "",
                    "use_agents": session.assistant_use_agents,
                })
                return

            if action == "call_assistant":
                assistant_id = payload.get("assistant_id") or session.active_assistant_id
                flow_id = payload.get("flow_id") or session.active_flow_id
                if not assistant_id or not flow_id:
                    await _reply(update, "Necesito assistant_id y flow_id para callAssistant.")
                    return
                await self._route(update, auth_ctx, "call_assistant", "HIGH", {
                    "flow_id": flow_id,
                    "assistant_id": assistant_id,
                    "input": payload.get("input", ""),
                    "use_agents": session.assistant_use_agents,
                })
                return

            if action == "stop_assistant":
                assistant_id = payload.get("assistant_id") or session.active_assistant_id
                flow_id = payload.get("flow_id") or session.active_flow_id
                if not assistant_id or not flow_id:
                    await _reply(update, "Necesito assistant_id y flow_id para stopAssistant.")
                    return
                await self._route(update, auth_ctx, "stop_assistant", "HIGH", {
                    "flow_id": flow_id,
                    "assistant_id": assistant_id,
                })
                return

            if action == "delete_assistant":
                assistant_id = payload.get("assistant_id") or session.active_assistant_id
                flow_id = payload.get("flow_id") or session.active_flow_id
                if not assistant_id or not flow_id:
                    await _reply(update, "Necesito assistant_id y flow_id para deleteAssistant.")
                    return
                await self._route(update, auth_ctx, "delete_assistant", "CRITICAL", {
                    "flow_id": flow_id,
                    "assistant_id": assistant_id,
                })
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
            session.ui_mode = "flow_draft"
            session.last_screen = "new_flow_draft"
            await self._store.upsert_session(session)
            await _reply(update, "✏️ *Nuevo Flow*\n\nEscribe tu objetivo para el nuevo flow.",
                {"inline_keyboard": [[{"text": "🔙 Home", "callback_data": "ui:home"}]]})
            return

        if self._settings.gateway_mode == "READ_ONLY":
            msg = READ_ONLY_BLOCK_MESSAGE + "\n\nPreview: objetivo: " + str(prompt)[:200]
            await _reply(update, msg)
            return

        # Route through mutation policy
        await self._route(
            update, auth_ctx, "create_flow", "HIGH",
            {"input": {"prompt": prompt}},
            intent=Intent.CREATE_FLOW_REQUEST,
        )

    async def _show_home(self, update: Update, session: TelegramSession) -> None:
        providers_raw = await self._fetch_providers()
        text, markup = home_screen(session, providers_raw, [], self._settings.gateway_mode)
        session.ui_mode = "home"
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
        result: str | tuple[str, Any],
    ) -> None:
        if isinstance(result, tuple):
            text, markup = result
        else:
            text, markup = result, None
        if markup is None and ("operador" in text.lower() or "PentAGI" in text or "flow activo" in text or "flows disponibles" in text or "marcha" in text or "estado" in text):
            markup = {"inline_keyboard": [[{"text": "📊 Flows", "callback_data": "ui:flows"}, {"text": "🔍 Help", "callback_data": "ui:help"}]]}
        session.last_screen = self._screen_for_action(action)
        await self._store.upsert_session(session)
        await _reply(update, text, markup)

    async def _route(
        self,
        update: Update,
        auth_ctx: AuthContext,
        action: str,
        risk: str,
        payload: dict[str, Any],
        intent: Intent | None = None,
    ) -> None:
        policy = self._policy().evaluate(action, Risk(risk.upper()), auth_ctx, payload)
        # Decision logging
        is_safe_local = action in {"operator_intro", "operator_identity", "operator_capabilities", "help", "unknown"}
        is_read_only_query = action in {"list_flows", "list_providers", "get_flow", "get_tasks", "get_logs", "get_terminal", "get_flow_status", "get_flow_summary", "get_recent_findings", "bind_flow", "unbind_flow", "view_terminal", "view_assistant"}
        is_mutation = action in self._mutation_actions()
        logger.info(
            "DECISION: raw_intent=%s action=%s safe_local=%s read_only_query=%s mutation=%s mode=%s allowed=%s requires_approval=%s blocked=%s",
            intent.name if intent else "N/A",
            action,
            is_safe_local,
            is_read_only_query,
            is_mutation,
            self._settings.gateway_mode,
            policy.allowed,
            policy.requires_approval,
            policy.blocked,
        )
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
        # create_flow no necesita flow_id — ejecuta mutation directa
        if action == "create_flow":
            raw = payload.get("input", payload)
            prompt = raw.get("prompt", raw) if isinstance(raw, dict) else raw
            result = await self._client.create_flow(
                str(prompt),
                model_provider=self._settings.pentagi_default_provider,
            )
            return f"✅ Flow creado: {result}"
        if action == "help" or action == "unknown":
            resp = payload.get("message") or "Puedo listar flows, abrir/bind flow, resumir, revisar hallazgos y crear aprobaciones."
            if ("operador" in resp.lower() or "PentAGI" in resp or "flow activo" in resp or "flows disponibles" in resp or "marcha" in resp or "estado" in resp):
                return resp, {"inline_keyboard": [[{"text": "📊 Flows", "callback_data": "ui:flows"}, {"text": "🔍 Help", "callback_data": "ui:help"}]]}
            # Texto libre sin flow/assistant activo → mostrar opciones
            if not flow_id:
                return resp, {"inline_keyboard": [
                    [{"text": "💬 Assistant Mode", "callback_data": "ui:assistant"}, {"text": "📊 Flows", "callback_data": "ui:flows"}],
                    [{"text": "🆕 Crear Flow", "callback_data": "ui:new_flow"}, {"text": "Help", "callback_data": "ui:help"}],
                ]}
            return resp, None
        if action == "operator_intro":
            resp = payload.get("message") or "PentAGI Gateway activo. Estás en READ_ONLY. Elige modo o consulta."
            return resp, {"inline_keyboard": [
                [{"text": "📊 Flows", "callback_data": "ui:flows"}, {"text": "📋 Tareas", "callback_data": "ui:tasks"}],
                [{"text": "🧾 Resumen", "callback_data": "ui:summary"}, {"text": "💬 Assistant Mode", "callback_data": "ui:assistant"}],
                [{"text": "⚙️ Solicitar ASSISTED_EXECUTION", "callback_data": "ui:request_approval"}],
                [{"text": "🔎 Help", "callback_data": "ui:help"}],
            ]}
        if action == "operator_identity":
            resp = payload.get("message") or "Soy PentAGI Gateway, tu asistente de orquestación de flows de ciberseguridad."
            return resp, None
        if action == "operator_capabilities":
            resp = payload.get("message") or "Puedo listar flows, activar/proveedores, crear flows, enviar inputs, ver logs, terminal y resumir hallazgos."
            return resp, None
        if action == "list_providers":
            try:
                providers = await self._client.list_providers() or await self._client.get_settings_providers()
                return format_providers(providers)
            except Exception as e:
                err = str(e).lower().replace("traceback", "").strip()
                err = re.sub(r"bearer\s+\S+", "", err)
                err = re.sub(r"\bsecret\b", "", err)
                err = re.sub(r"\s+", " ", err).strip()
                return f"PentAGI rechazó la conexión: {err[:120]}"
        if action == "list_flows":
            try:
                return format_flow_list(await self._client.list_flows())
            except Exception as e:
                err = str(e).lower().replace("traceback", "").strip()
                err = re.sub(r"bearer\s+\S+", "", err)
                err = re.sub(r"\bsecret\b", "", err)
                err = re.sub(r"\s+", " ", err).strip()
                return f"PentAGI rechazó la conexión: {err[:120]}"
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
        if action == "stop_local":
            session = await self._store.ensure_session(auth_ctx.chat_id, auth_ctx.user_id, auth_ctx.role.value)
            session.active_flow_id = None
            session.active_flow_status = None
            await self._store.upsert_session(session)
            return "✅ No se ejecutó ninguna acción. Flow desvinculado localmente."
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
        if action == "get_assistants":
            if not flow_id:
                return "Necesito un flow_id para listar assistants."
            try:
                assistants = await self._client.get_assistants(flow_id)
                if not assistants:
                    return "No hay assistants en este flow. Crea uno para empezar."
                lines = ["🤖 Assistants disponibles:"]
                for a in assistants:
                    lines.append(f"  • {a.get('title', 'N/A')} (ID: {a.get('id', 'N/A')}) [{a.get('status', '?')}]")
                return "\n".join(lines)
            except Exception as e:
                err = str(e).lower().replace("traceback", "").strip()
                err = re.sub(r"bearer\s+\S+", "", err)
                err = re.sub(r"\bsecret\b", "", err)
                err = re.sub(r"\s+", " ", err).strip()
                return f"PentAGI rechazó la conexión: {err[:120]}"
        if action == "put_user_input" and flow_id:
            input_text = payload.get("input", "")
            if not str(input_text).strip():
                return f"Bloqueado: putUserInput requiere texto no vacío."
            result = await self._client.put_user_input(flow_id, input_text)
            return f"✅ Input enviado: {result}"
        return "Acción de lectura no soportada."

    async def _execute_mutation(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            return {"error": "Cliente PentAGI no configurado"}
        if action == "create_flow":
            raw = payload.get("input", payload)
            prompt = raw.get("prompt", raw) if isinstance(raw, dict) else raw
            result = await self._client.create_flow(
                str(prompt),
                model_provider=self._settings.pentagi_default_provider,
            )
            # Set ui_mode based on flow status
            return result
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
        if action == "create_assistant":
            result = await self._client.create_assistant(
                flow_id=payload["flow_id"],
                model_provider=payload.get("model_provider", "qwen"),
                input_text=payload.get("input", ""),
                use_agents=payload.get("use_agents", False),
            )
            # Extract assistant from FlowAssistant { flow, assistant }
            assistant_data = result.get("assistant", {})
            return {"assistant": assistant_data, "raw": result, "approved": True}
        if action == "call_assistant":
            return await self._client.call_assistant(
                flow_id=payload["flow_id"],
                assistant_id=payload["assistant_id"],
                input_text=payload.get("input", ""),
                use_agents=payload.get("use_agents", False),
            )
        if action == "stop_assistant":
            return await self._client.stop_assistant(
                flow_id=payload["flow_id"],
                assistant_id=payload["assistant_id"],
            )
        if action == "delete_assistant":
            return await self._client.delete_assistant(
                flow_id=payload["flow_id"],
                assistant_id=payload["assistant_id"],
            )
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
            "create_assistant", "call_assistant", "stop_assistant", "delete_assistant",
            "confirm_new_flow",
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
