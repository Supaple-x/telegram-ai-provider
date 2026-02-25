import asyncpg
import logging
from config.settings import settings

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """Initialize database connection pool.

    Schema is managed exclusively by Alembic migrations (alembic/versions/).
    Run ``alembic upgrade head`` before first start.
    """
    global pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)

    # Verify connectivity
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")

    logger.info("Database pool initialized successfully")


async def close_db() -> None:
    """Close database connection pool."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database connection closed")


def get_pool() -> asyncpg.Pool:
    """Get database connection pool."""
    if pool is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return pool
