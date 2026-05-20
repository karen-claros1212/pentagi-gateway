"""PentAGI Gateway entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

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
    logger.info("settings=%s", settings)
    Path(settings.gateway_sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    store = SessionStore(settings.gateway_sqlite_path)
    await store.open()
    client = PentagiClient(settings.graphql_url, settings.pentagi_api_token, settings.pentagi_verify_tls)
    auth = AuthProvider(settings.allowed_user_ids, settings.allowed_chat_ids)
    dispatcher = Dispatcher(auth, store, RateLimiter(), settings=settings, client=client)
    bot = TelegramBot(settings.telegram_bot_token, client, auth, store, dispatcher, settings.allowed_user_ids)

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
