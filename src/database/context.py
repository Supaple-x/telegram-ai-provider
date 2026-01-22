import logging
from config.settings import settings
from src.database.connection import get_pool

logger = logging.getLogger(__name__)


async def ensure_user(telegram_id: int, username: str | None = None) -> None:
    """Create user if not exists."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET username = $2
            """,
            telegram_id,
            username,
        )


async def get_context(telegram_id: int) -> list[dict]:
    """Get conversation context for user (last N messages)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content FROM messages
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            telegram_id,
            settings.max_context_messages,
        )

    # Reverse to get chronological order
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def add_message(telegram_id: int, role: str, content: str) -> None:
    """Add message to conversation context."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (user_id, role, content)
            VALUES ($1, $2, $3)
            """,
            telegram_id,
            role,
            content,
        )


async def clear_context(telegram_id: int) -> int:
    """Clear conversation context for user. Returns number of deleted messages."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM messages WHERE user_id = $1",
            telegram_id,
        )
        # Result format: "DELETE N"
        count = int(result.split()[-1])
        logger.info(f"Cleared {count} messages for user {telegram_id}")
        return count
