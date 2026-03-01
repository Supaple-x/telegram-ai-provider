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

    # Safety-net: create all tables if migrations were not applied
    async with pool.acquire() as conn:
        # users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # messages table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_id
            ON messages(user_id)
        """)
        
        # message_attachments table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_attachments (
                id SERIAL PRIMARY KEY,
                message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
                attachment_type VARCHAR(20) NOT NULL DEFAULT 'image',
                data TEXT NOT NULL,
                media_type VARCHAR(50) NOT NULL DEFAULT 'image/jpeg',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_attachments_message_id
            ON message_attachments(message_id)
        """)
        
        # user_memory table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                content VARCHAR(500) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_memory_user_id
            ON user_memory(user_id)
        """)
        
        # user_preferences table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
                preferred_model VARCHAR(20) NOT NULL DEFAULT 'claude',
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # video_generations table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS video_generations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                prompt TEXT NOT NULL,
                mode VARCHAR(20) NOT NULL DEFAULT 'text-to-video',
                duration VARCHAR(5) NOT NULL DEFAULT '5',
                resolution VARCHAR(10) NOT NULL DEFAULT '720p',
                aspect_ratio VARCHAR(10) NOT NULL DEFAULT '16:9',
                video_url TEXT,
                seed INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_video_generations_user_id
            ON video_generations(user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_video_generations_created_at
            ON video_generations(created_at)
        """)

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
