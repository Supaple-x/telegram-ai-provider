import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from src.database.connection import init_db, close_db
from src.database.context import cleanup_old_messages
from src.services.claude import init_client
from src.services.openai_fallback import init_openai_client
from src.services.image_gen import init_image_client
from src.services.transcription import init_transcription_client
from src.services.video_gen import init_video_client
from src.middleware import AuthMiddleware, ThrottleMiddleware
from src.handlers import (
    commands_router,
    messages_router,
    image_router,
    voice_router,
    search_router,
    memory_router,
    video_router,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def periodic_cleanup() -> None:
    """Background task: cleanup old messages every 6 hours."""
    while True:
        try:
            await asyncio.sleep(6 * 60 * 60)  # 6 hours
            deleted = await cleanup_old_messages()
            if deleted:
                logger.info(f"Periodic cleanup: removed {deleted} old messages")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")


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

    logger.info("Initializing OpenAI fallback (GPT-5.2)...")
    init_openai_client()

    logger.info("Initializing image generation...")
    init_image_client()

    logger.info("Initializing voice transcription...")
    init_transcription_client()

    logger.info("Initializing video generation...")
    init_video_client()

    # Create bot and dispatcher
    bot = Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Register middleware (order matters: auth first, then throttle)
    dp.message.outer_middleware(AuthMiddleware())
    dp.callback_query.outer_middleware(AuthMiddleware())
    dp.message.outer_middleware(ThrottleMiddleware())

    # Register routers (order matters: commands first, then specialized, then catch-all text)
    dp.include_router(commands_router)
    dp.include_router(memory_router)
    dp.include_router(search_router)
    dp.include_router(image_router)
    dp.include_router(voice_router)
    dp.include_router(video_router)
    dp.include_router(messages_router)

    # Log access control status
    if settings.allowed_users:
        logger.info(f"Access control: {len(settings.allowed_users)} allowed users")
    else:
        logger.warning("Access control: DISABLED (any user can access the bot)")

    logger.info(f"Rate limit: {settings.rate_limit_messages} messages per {settings.rate_limit_window}s")

    # Start background tasks
    cleanup_task = asyncio.create_task(periodic_cleanup())

    # Run initial cleanup on startup
    try:
        deleted = await cleanup_old_messages()
        if deleted:
            logger.info(f"Startup cleanup: removed {deleted} old messages")
    except Exception as e:
        logger.error(f"Startup cleanup failed: {e}")

    # Graceful shutdown handler
    async def shutdown() -> None:
        logger.info("Shutting down...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
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
