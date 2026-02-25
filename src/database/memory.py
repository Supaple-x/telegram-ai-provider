import logging
from src.database.connection import get_pool

logger = logging.getLogger(__name__)

MAX_MEMORIES_PER_USER = 10


async def get_memories(telegram_id: int) -> list[dict]:
    """Get all memories for a user, ordered by creation date."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, created_at FROM user_memory
            WHERE user_id = $1
            ORDER BY created_at ASC
            """,
            telegram_id,
        )
    return [{"id": row["id"], "content": row["content"], "created_at": row["created_at"]} for row in rows]


async def get_memory_texts(telegram_id: int) -> list[str]:
    """Get just the memory text contents for inclusion in system prompt."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content FROM user_memory
            WHERE user_id = $1
            ORDER BY created_at ASC
            """,
            telegram_id,
        )
    return [row["content"] for row in rows]


async def add_memory(telegram_id: int, content: str) -> str:
    """Add a memory for a user.

    Returns:
        Status message: success, duplicate, or limit reached.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Check for duplicate
        existing = await conn.fetchval(
            "SELECT id FROM user_memory WHERE user_id = $1 AND content = $2",
            telegram_id,
            content,
        )
        if existing:
            return "duplicate"

        # Check limit
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM user_memory WHERE user_id = $1",
            telegram_id,
        )
        if count >= MAX_MEMORIES_PER_USER:
            return "limit"

        await conn.execute(
            "INSERT INTO user_memory (user_id, content) VALUES ($1, $2)",
            telegram_id,
            content,
        )
        logger.info(f"Memory added for user {telegram_id}: {content[:50]}...")
        return "ok"


async def remove_memory(telegram_id: int, memory_id: int) -> bool:
    """Remove a memory by ID. Returns True if deleted."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_memory WHERE id = $1 AND user_id = $2",
            memory_id,
            telegram_id,
        )
        deleted = int(result.split()[-1]) > 0
        if deleted:
            logger.info(f"Memory {memory_id} removed for user {telegram_id}")
        return deleted


async def clear_memories(telegram_id: int) -> int:
    """Clear all memories for a user. Returns number deleted."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_memory WHERE user_id = $1",
            telegram_id,
        )
        count = int(result.split()[-1])
        if count > 0:
            logger.info(f"Cleared {count} memories for user {telegram_id}")
        return count
