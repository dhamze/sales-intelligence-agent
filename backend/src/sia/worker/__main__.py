"""Run the background worker:  uv run python -m sia.worker"""

import asyncio
import platform

import structlog

from sia.core.config import get_settings
from sia.core.logging import configure_logging
from sia.worker import configured_app, runtime

logger = structlog.get_logger("sia.worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    runtime.init(settings)
    app = configured_app(settings)
    logger.info("worker_starting", concurrency=settings.worker_concurrency)
    try:
        async with app.open_async():
            await app.run_worker_async(concurrency=settings.worker_concurrency)
    finally:
        await runtime.dispose()
        logger.info("worker_stopped")


if __name__ == "__main__":
    if platform.system() == "Windows":  # runtime check: both branches stay type-checked
        # psycopg's async mode cannot use Windows' default (Proactor) event loop.
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())
