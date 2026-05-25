"""ServiceManager — DI container with lazy init and lifecycle.

Following Dola App Pattern #3: central wiring, dependency inversion,
decoupled construction from business logic.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from ..pentagi.client import PentagiClient
from ..security.rate_limiter import RateLimiter
from .approvals import ApprovalStore
from .auth import AuthProvider
from .dispatcher import Dispatcher
from .interfaces import IAuthProvider, IPentagiClient, IRateLimiter, ISessionStore
from .session import SessionStore
from ..llm import Brain
from ..telegram.bot import TelegramBot

logger = logging.getLogger(__name__)


class ServiceManager:
    """Wires all gateway services together.

    Provides lazy initialization of all services and handles lifecycle.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store: ISessionStore | None = None
        self._client: IPentagiClient | None = None
        self._auth: IAuthProvider | None = None
        self._rate: IRateLimiter | None = None
        self._approvals: ApprovalStore | None = None
        self._dispatcher: Dispatcher | None = None
        self._brain: Brain | None = None
        self._bot: TelegramBot | None = None

    # -- Services (lazy) ------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def store(self) -> ISessionStore:
        if self._store is None:
            self._store = SessionStore(self._settings.gateway_sqlite_path)
        return self._store

    @property
    def client(self) -> IPentagiClient:
        if self._client is None:
            self._client = PentagiClient(
                self._settings.graphql_url,
                self._settings.pentagi_api_token,
                self._settings.pentagi_verify_tls,
                ssl_ca_path=self._settings.pentagi_tls_ca_path or None,
                tls_pins=self._settings.pentagi_tls_pins or "",
            )
        return self._client

    @property
    def auth(self) -> IAuthProvider:
        if self._auth is None:
            self._auth = AuthProvider(
                self._settings.allowed_user_ids,
                self._settings.allowed_chat_ids,
            )
        return self._auth

    @property
    def rate_limiter(self) -> IRateLimiter:
        if self._rate is None:
            self._rate = RateLimiter()
        return self._rate

    @property
    def approvals(self) -> ApprovalStore:
        if self._approvals is None:
            self._approvals = ApprovalStore(
                self.store,
                ttl_seconds=self._settings.approval_ttl_seconds,
            )
        return self._approvals

    @property
    def brain(self) -> Brain:
        if self._brain is None:
            self._brain = Brain(
                enabled=self._settings.llm_enabled,
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key,
                model=self._settings.llm_model,
            )
        return self._brain

    @property
    def dispatcher(self) -> Dispatcher:
        if self._dispatcher is None:
            self._dispatcher = Dispatcher(
                auth=self.auth,
                store=self.store,
                rate_limiter=self.rate_limiter,
                settings=self._settings,
                client=self.client,
                brain=self.brain,
            )
        return self._dispatcher

    @property
    def bot(self) -> TelegramBot:
        if self._bot is None:
            self._bot = TelegramBot(
                token=self._settings.telegram_bot_token,
                dispatcher=self.dispatcher,
                allowed_users=self._settings.allowed_user_ids,
            )
        return self._bot

    # -- Lifecycle ------------------------------------------------------

    async def open(self) -> None:
        """Open all async services."""
        await self.store.open()
        logger.info("ServiceManager: store opened")

    async def close(self) -> None:
        """Close all async services in reverse order."""
        errors: list[Exception] = []
        if self._bot is not None:
            try:
                await self._bot.stop()
            except Exception as exc:
                errors.append(exc)
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                errors.append(exc)
        if self._store is not None:
            try:
                await self._store.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            msg = "; ".join(str(e) for e in errors)
            logger.error("ServiceManager close errors: %s", msg)
