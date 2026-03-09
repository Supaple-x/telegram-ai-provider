"""Allowed users management with in-memory cache."""

import logging

from src.database.connection import get_pool

logger = logging.getLogger(__name__)

# In-memory cache of approved user IDs (loaded at startup)
_approved_ids: set[int] = set()


def is_approved(telegram_id: int) -> bool:
    """Check if user is in the approved cache (sync, fast)."""
    return telegram_id in _approved_ids


async def load_approved_users() -> int:
    """Load all approved user IDs from DB into cache. Returns count."""
    global _approved_ids
    pool = get_pool()
    rows = await pool.fetch("SELECT telegram_id FROM allowed_users")
    _approved_ids = {row["telegram_id"] for row in rows}
    return len(_approved_ids)


async def approve_user(telegram_id: int, phone: str, username: str | None) -> None:
    """Add user to allowed list (DB + cache)."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO allowed_users (telegram_id, phone, username, approved_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (telegram_id) DO UPDATE
        SET phone = $2, username = $3, approved_at = NOW()
        """,
        telegram_id, phone, username,
    )
    _approved_ids.add(telegram_id)
    logger.info(f"User approved: {telegram_id} (@{username}, {phone})")
