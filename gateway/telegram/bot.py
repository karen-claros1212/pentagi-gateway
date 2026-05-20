"""Telegram bot setup and polling."""

from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from ..core.auth import AuthProvider
from ..core.dispatcher import Dispatcher
from ..core.session import SessionStore
from ..pentagi.client import PentagiClient
from ..security import redact
from .handlers import CommandHandlers

logger = logging.getLogger(__name__)


class TelegramBot:
    """Wraps python-telegram-bot with auth + dispatch."""

    def __init__(
        self,
        token: str,
        client: PentagiClient,
        auth: AuthProvider,
        store: SessionStore,
        dispatcher: Dispatcher,
        allowed_users: list[int],
    ) -> None:
        del auth, store
        self._allowed = set(allowed_users)
        self._handlers = CommandHandlers(client, dispatcher)
        self._app = Application.builder().token(token).build()
        self._register()

    def _register(self) -> None:
        h = self._handlers
        self._app.add_handler(CommandHandler("start", h.start))
        self._app.add_handler(CommandHandler("help", h.help_cmd))
        self._app.add_handler(CommandHandler("providers", h.providers))
        self._app.add_handler(CommandHandler("flows", h.flows))
        self._app.add_handler(CommandHandler("flow", h.flow))
        self._app.add_handler(CommandHandler("tasks", h.tasks))
        self._app.add_handler(CommandHandler("logs", h.logs))
        self._app.add_handler(CommandHandler("terminal", h.terminal))
        self._app.add_handler(CommandHandler("bind", h.bind))
        self._app.add_handler(CommandHandler("unbind", h.unbind))
        self._app.add_handler(CommandHandler("active", h.active))
        self._app.add_handler(CommandHandler("create_flow", h.create_flow))
        self._app.add_handler(CommandHandler("send", h.send))
        self._app.add_handler(CommandHandler("stop_flow", h.stop_flow))
        self._app.add_handler(CommandHandler("finish_flow", h.finish_flow))
        self._app.add_handler(CommandHandler("rename_flow", h.rename_flow))
        self._app.add_handler(CommandHandler("delete_flow", h.delete_flow))
        self._app.add_handler(CommandHandler("confirm", h.confirm))
        self._app.add_handler(CommandHandler("confirm_delete", h.confirm_delete))
        self._app.add_handler(CommandHandler("deny", h.deny))
        self._app.add_handler(CommandHandler("watch", h.watch))
        self._app.add_handler(CommandHandler("unwatch", h.unwatch))
        self._app.add_handler(CommandHandler("watch_status", h.watch_status))
        self._app.add_handler(CommandHandler("summary", h.summary))
        self._app.add_handler(CommandHandler("report", h.report))
        self._app.add_handler(CallbackQueryHandler(h.callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, h.text))
        self._app.add_handler(MessageHandler(filters.ALL, self._unauth), group=-1)
        self._app.add_error_handler(self._on_error)

    async def _unauth(self, update, context) -> None:
        del context
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in self._allowed:
            await update.message.reply_text("⛔ Unauthorized.")

    async def _on_error(self, update, context) -> None:
        err = redact(str(context.error))
        logger.error("Telegram error: %s", err)
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(f"⚠️ Error: {err[:300]}")
            except Exception:
                pass

    async def start_polling(self) -> None:
        logger.info("Starting Telegram polling ...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        logger.info("Stopping bot ...")
        await self._app.stop()
        await self._app.shutdown()
