"""Telegram handlers: natural-language first, commands as fallback."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..core.dispatcher import Dispatcher
from ..pentagi.client import PentagiClient


class CommandHandlers:
    """Read-only commands plus controlled approval commands."""

    def __init__(self, client: PentagiClient, dispatcher: Dispatcher) -> None:
        self._client = client
        self._dispatch = dispatcher

    async def text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_text(update, ctx, update.message.text or "")

    async def callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        await self._dispatch.handle_text(update, ctx, query.data or "")

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self.help_cmd(update, ctx)

    async def help_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_command_action(update, ctx, "help", {"message": help_text()})

    async def providers(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_command_action(update, ctx, "list_providers")

    async def flows(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_command_action(update, ctx, "list_flows")

    async def flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_flow")

    async def tasks(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_tasks")

    async def logs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_logs")

    async def terminal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_terminal")

    async def bind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "bind_flow")

    async def unbind(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_command_action(update, ctx, "unbind_flow")

    async def active(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_text(update, ctx, "qué está haciendo")

    async def create_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        prompt = " ".join(ctx.args) if ctx.args else "crear flow"
        await self._dispatch.handle_command_action(update, ctx, "create_flow", {"input": {"prompt": prompt}}, risk="HIGH")

    async def send(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = " ".join(ctx.args)
        await self._dispatch.handle_text(update, ctx, f"dile que {text}" if text else "dile que continúe")

    async def stop_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "stop_flow", risk="HIGH")

    async def finish_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "finish_flow", risk="HIGH")

    async def rename_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = list(ctx.args)
        flow_id = args[0] if args else None
        name = " ".join(args[1:]) if len(args) > 1 else ""
        await self._dispatch.handle_command_action(update, ctx, "rename_flow", {"flow_id": flow_id, "name": name}, risk="HIGH")

    async def delete_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "delete_flow", risk="CRITICAL")

    async def confirm(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.confirm(update, ctx.args[0] if ctx.args else "", delete=False)

    async def confirm_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.confirm(update, ctx.args[0] if ctx.args else "", delete=True)

    async def deny(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.deny(update, ctx.args[0] if ctx.args else "")

    async def watch(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "watch_flow")

    async def unwatch(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "unwatch_flow")

    async def watch_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._dispatch.handle_command_action(update, ctx, "help", {"message": "Watch status: subscriptions are disabled unless PENTAGI_SUBSCRIPTIONS_ENABLED=true."})

    async def summary(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_flow_summary")

    async def report(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._with_flow(update, ctx, "get_recent_findings")

    async def _with_flow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str, risk: str = "LOW") -> None:
        flow_id = ctx.args[0] if getattr(ctx, "args", None) else None
        await self._dispatch.handle_command_action(update, ctx, action, {"flow_id": flow_id}, risk=risk)


def help_text() -> str:
    return (
        "🤖 PentAGI Gateway — Natural Language First\n\n"
        "Ejemplos: 'muéstrame los flows', 'abre este flow <id>', 'resume el flow', "
        "'qué encontró', 'crea un flow...', 'dile que continúe'.\n\n"
        "Comandos fallback: /flows /flow /tasks /logs /terminal /bind /summary /report "
        "/create_flow /send /stop_flow /finish_flow /rename_flow /delete_flow "
        "/confirm /confirm-delete /deny /watch /unwatch."
    )
