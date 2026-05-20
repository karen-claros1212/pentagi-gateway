"""PentAGI Gateway — entry point."""

from __future__ import annotations

import asyncio
import logging
import sys

from .config import Settings
from .core.auth import AuthProvider
from .core.dispatcher import Dispatcher
from .core.session import SessionStore
from .pentagi.client import PentagiClient
from .security.rate_limiter import RateLimiter
from .telegram.bot import TelegramBot

logger = logging.getLogger("gateway")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def amain() -> None:
    settings = Settings()
    try:
        settings.validate()
    except ValueError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(settings.gateway_log_level)
    logger.info("mode=%s endpoint=%s", settings.gateway_mode, settings.graphql_url)

    # DB
    store = SessionStore(settings.gateway_sqlite_path)
    await store.open()

    # PentAGI client
    client = PentagiClient(
        graphql_url=settings.graphql_url,
        api_token=settings.pentagi_api_token,
        verify_tls=settings.pentagi_verify_tls,
    )

    # Auth
    auth = AuthProvider(
        allowed_users=settings.allowed_user_ids,
        allowed_chats=settings.allowed_chat_ids,
    )

    # Dispatcher
    dispatcher = Dispatcher(auth, store, RateLimiter())

    # Bot
    bot = TelegramBot(
        token=settings.telegram_bot_token,
        client=client,
        auth=auth,
        store=store,
        dispatcher=dispatcher,
        allowed_users=settings.allowed_user_ids,
    )

    try:
        await bot.start_polling()
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await bot.stop()
        await client.close()
        await store.close()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
