import logging
from config.settings import settings
from src.database.connection import get_pool

logger = logging.getLogger(__name__)

# In-memory cache of known users to avoid DB writes on every message
_known_users: set[int] = set()


async def ensure_user(telegram_id: int, username: str | None = None) -> None:
    """Create user if not exists. Caches known users to reduce DB writes."""
    if telegram_id in _known_users:
        return

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
    _known_users.add(telegram_id)


# Max number of images to include in context (to control API payload size)
MAX_CONTEXT_IMAGES = 3


async def get_context(telegram_id: int) -> list[dict]:
    """Get conversation context for user (last N messages).

    Returns list of dicts with 'role', 'content', and optionally 'image_data'
    (tuple of base64_data, media_type) for the most recent images.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.role, m.content, ma.data AS image_base64, ma.media_type
            FROM messages m
            LEFT JOIN message_attachments ma ON ma.message_id = m.id
            WHERE m.user_id = $1
            ORDER BY m.created_at DESC
            LIMIT $2
            """,
            telegram_id,
            settings.max_context_messages,
        )

    # rows are DESC (newest first) — keep only MAX_CONTEXT_IMAGES most recent images
    image_count = 0
    entries = []
    for row in rows:
        entry = {"role": row["role"], "content": row["content"]}
        if row["image_base64"] and image_count < MAX_CONTEXT_IMAGES:
            entry["image_data"] = (row["image_base64"], row["media_type"])
            image_count += 1
        entries.append(entry)

    return list(reversed(entries))  # chronological order


async def add_message(
    telegram_id: int,
    role: str,
    content: str,
    image_data: tuple[str, str] | None = None,
) -> None:
    """Add message to conversation context.

    Args:
        telegram_id: User's Telegram ID
        role: Message role ('user' or 'assistant')
        content: Message text content
        image_data: Optional (base64_data, media_type) to store as attachment
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if image_data:
            base64_data, media_type = image_data
            async with conn.transaction():
                msg_id = await conn.fetchval(
                    "INSERT INTO messages (user_id, role, content) "
                    "VALUES ($1, $2, $3) RETURNING id",
                    telegram_id,
                    role,
                    content,
                )
                await conn.execute(
                    "INSERT INTO message_attachments (message_id, data, media_type) "
                    "VALUES ($1, $2, $3)",
                    msg_id,
                    base64_data,
                    media_type,
                )
        else:
            await conn.execute(
                "INSERT INTO messages (user_id, role, content) "
                "VALUES ($1, $2, $3)",
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


async def cleanup_old_messages() -> int:
    """Delete messages older than TTL. Returns number of deleted messages."""
    if settings.messages_ttl_days <= 0:
        return 0

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM messages WHERE created_at < NOW() - INTERVAL '1 day' * $1",
            settings.messages_ttl_days,
        )
        count = int(result.split()[-1])
        if count > 0:
            logger.info(f"Cleaned up {count} old messages (>{settings.messages_ttl_days} days)")
        return count


async def get_stats() -> dict:
    """Get database statistics for /stats command (single query)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users_total,
                (SELECT COUNT(*) FROM messages) AS messages_total,
                (SELECT COUNT(DISTINCT user_id) FROM messages
                 WHERE created_at > NOW() - INTERVAL '1 day') AS active_today
            """
        )
    return {
        "users_total": row["users_total"],
        "messages_total": row["messages_total"],
        "active_today": row["active_today"],
    }
