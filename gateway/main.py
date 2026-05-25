"""PentAGI Gateway entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from .config import Settings
from .core.service_manager import ServiceManager

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

    services = ServiceManager(settings)
    await services.open()
    bot = services.bot

    try:
        await bot.start_polling()
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await services.close()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
