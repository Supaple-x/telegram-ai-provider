import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from src.database.connection import init_db, close_db
from src.services.claude import init_client
from src.handlers import commands_router, messages_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    # Validate settings
    try:
        settings.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Initialize services
    logger.info("Initializing database...")
    await init_db()

    logger.info("Initializing Anthropic client...")
    init_client()

    # Create bot and dispatcher
    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Register routers
    dp.include_router(commands_router)
    dp.include_router(messages_router)

    # Graceful shutdown handler
    async def shutdown() -> None:
        logger.info("Shutting down...")
        await close_db()
        await bot.session.close()

    # Handle signals
    loop = asyncio.get_event_loop()

    def signal_handler() -> None:
        loop.create_task(shutdown())
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        logger.info("Starting bot...")
        await dp.start_polling(bot)
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
