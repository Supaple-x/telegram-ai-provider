"""CRUD for user_preferences (model switching)."""

import logging

from src.database.connection import get_pool

logger = logging.getLogger(__name__)

# In-memory cache: telegram_id → preferred_model
_model_cache: dict[int, str] = {}

VALID_MODELS = {"claude", "openai"}
DEFAULT_MODEL = "claude"


async def get_preferred_model(telegram_id: int) -> str:
    """Return preferred model for user ('claude' or 'openai'). Cached in memory."""
    if telegram_id in _model_cache:
        return _model_cache[telegram_id]

    pool = get_pool()
    async with pool.acquire() as conn:
        model = await conn.fetchval(
            "SELECT preferred_model FROM user_preferences WHERE user_id = $1",
            telegram_id,
        )

    result = model if model in VALID_MODELS else DEFAULT_MODEL
    _model_cache[telegram_id] = result
    return result


async def set_preferred_model(telegram_id: int, model: str) -> None:
    """Set preferred model for user. Updates cache."""
    if model not in VALID_MODELS:
        raise ValueError(f"Invalid model: {model}. Valid: {VALID_MODELS}")

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_preferences (user_id, preferred_model, updated_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (user_id)
               DO UPDATE SET preferred_model = $2, updated_at = NOW()""",
            telegram_id,
            model,
        )

    _model_cache[telegram_id] = model
    logger.info(f"User {telegram_id} switched model to {model}")
