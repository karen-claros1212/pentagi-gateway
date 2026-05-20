"""Telegram command handlers — Phase 1 read-only."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ..core.dispatcher import Dispatcher
from ..pentagi.client import PentagiClient
from .formatter import (
    format_flow_detail,
    format_flow_list,
    format_logs,
    format_providers,
    format_tasks,
    format_terminal_logs,
)

logger = logging.getLogger(__name__)


class CommandHandlers:
    """All read-only commands, bound to a dispatcher & client."""

    def __init__(self, client: PentagiClient, dispatcher: Dispatcher) -> None:
        self._client = client
        self._dispatch = dispatcher

    async def _reply(self, update: Update, text: str) -> None:
        await update.message.reply_text(text)

    # ── /start ───────────────────────────────────────────────────

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "start", self._do_start)

    async def _do_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply(update,
            "🤖 *PentAGI Gateway* — READ-ONLY\n\n"
            "Commands:\n"
            "/providers — LLM providers\n"
            "/flows — all flows\n"
            "/flow `<id>` — flow detail\n"
            "/tasks `<flow_id>` — tasks\n"
            "/logs `<flow_id>` — message logs\n"
            "/terminal `<flow_id>` — terminal logs\n"
            "/bind `<flow_id>` — bind to active flow\n"
            "/unbind — clear active flow\n"
            "/active — show bound flow\n"
            "/help — this message"
        )

    async def help_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.start(update, ctx)

    # ── /providers ───────────────────────────────────────────────

    async def providers(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "providers", self._do_providers)

    async def _do_providers(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        providers = await self._client.list_providers() or await self._client.get_settings_providers()
        await self._reply(update, format_providers(providers))

    # ── /flows ───────────────────────────────────────────────────

    async def flows(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "flows", self._do_flows)

    async def _do_flows(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        flows = await self._client.list_flows()
        await self._reply(update, format_flow_list(flows))

    # ── /flow <id> ───────────────────────────────────────────────

    async def flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "flow", self._do_flow)

    async def _do_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await self._reply(update, "Usage: /flow <flow_id>")
            return
        f = await self._client.get_flow(args[0])
        await self._reply(update, format_flow_detail(f))

    # ── /tasks <flow_id> ─────────────────────────────────────────

    async def tasks(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "tasks", self._do_tasks)

    async def _do_tasks(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await self._reply(update, "Usage: /tasks <flow_id>")
            return
        tasks = await self._client.get_tasks(args[0])
        await self._reply(update, format_tasks(tasks))

    # ── /logs <flow_id> ──────────────────────────────────────────

    async def logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "logs", self._do_logs)

    async def _do_logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await self._reply(update, "Usage: /logs <flow_id>")
            return
        entries = await self._client.get_message_logs(args[0], limit=20)
        await self._reply(update, format_logs(entries))

    # ── /terminal <flow_id> ──────────────────────────────────────

    async def terminal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "terminal", self._do_terminal)

    async def _do_terminal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await self._reply(update, "Usage: /terminal <flow_id>")
            return
        entries = await self._client.get_terminal_logs(args[0], limit=30)
        await self._reply(update, format_terminal_logs(entries))

    # ── /bind <flow_id> ──────────────────────────────────────────

    async def bind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "bind", self._do_bind)

    async def _do_bind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args:
            await self._reply(update, "Usage: /bind <flow_id>")
            return
        fid = args[0]
        await self._dispatch._store.bind_flow(
            update.effective_chat.id, update.effective_user.id, fid
        )
        await self._reply(update, f"✅ Bound to flow `{fid}`.")

    # ── /unbind ──────────────────────────────────────────────────

    async def unbind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "unbind", self._do_unbind)

    async def _do_unbind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from ..core.session import TelegramSession
        ses = TelegramSession(chat_id=update.effective_chat.id, user_id=update.effective_user.id, active_flow_id=None)
        await self._dispatch._store.upsert_session(ses)
        await self._reply(update, "✅ Unbound from flow.")

    # ── /active ──────────────────────────────────────────────────

    async def active(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.dispatch(update, ctx, "active", self._do_active)

    async def _do_active(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        ses = await self._dispatch._store.get_session(
            update.effective_chat.id, update.effective_user.id
        )
        if ses and ses.active_flow_id:
            await self._reply(update, f"Active flow: `{ses.active_flow_id}`")
        else:
            await self._reply(update, "No active flow bound. Use /bind <flow_id>")
