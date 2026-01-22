import asyncpg
import logging
from config.settings import settings

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """Initialize database connection pool and create tables."""
    global pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
        """)

    logger.info("Database initialized successfully")


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
