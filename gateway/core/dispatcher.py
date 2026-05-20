"""Command dispatcher — auth, rate-limit, audit, dispatch."""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from telegram import Update
from telegram.ext import ContextTypes

from ..core.auth import AuthProvider, Role
from ..core.session import SessionStore
from ..security.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class Dispatcher:
    """Middleware between Telegram handlers and business logic."""

    def __init__(
        self,
        auth: AuthProvider,
        store: SessionStore,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._auth = auth
        self._store = store
        self._rate = rate_limiter or RateLimiter()

    async def dispatch(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]],
        risk: str = "low",
    ) -> None:
        """Validate, rate-limit, audit, then run handler."""
        uid = update.effective_user.id if update.effective_user else 0
        cid = update.effective_chat.id if update.effective_chat else 0

        # Auth
        if not self._auth.is_authorized(uid, cid):
            logger.warning("Unauthorized attempt uid=%d cid=%d action=%s", uid, cid, action)
            await update.message.reply_text("⛔ Unauthorized.")
            return

        role = self._auth.resolve_role(uid)
        ctx = self._auth.build_context(uid, cid)

        # Rate limit (10/min per user)
        if not self._rate.is_allowed(str(uid)):
            logger.info("Rate limited uid=%d action=%s", uid, action)
            await update.message.reply_text("⏳ Rate limited. Try again in a moment.")
            return

        # Audit
        await self._store.audit(uid, cid, action, risk=risk, allowed=True)

        # Execute
        await handler(update, context)
