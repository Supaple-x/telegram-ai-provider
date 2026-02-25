import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config.settings import settings

logger = logging.getLogger(__name__)


class ThrottleMiddleware(BaseMiddleware):
    """Per-user rate limiting middleware.

    Limits the number of messages a user can send within a time window.
    Only applies to Message events (not callbacks).
    Uses deque for O(1) cleanup of expired timestamps.
    """

    def __init__(self) -> None:
        self._user_timestamps: dict[int, deque[float]] = {}

    def _get_timestamps(self, user_id: int) -> deque[float]:
        """Get or create timestamp deque for a user."""
        if user_id not in self._user_timestamps:
            self._user_timestamps[user_id] = deque()
        return self._user_timestamps[user_id]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        now = time.monotonic()
        timestamps = self._get_timestamps(user.id)
        window = settings.rate_limit_window

        # O(1) amortized: pop expired timestamps from the left
        while timestamps and now - timestamps[0] >= window:
            timestamps.popleft()

        if len(timestamps) >= settings.rate_limit_messages:
            logger.warning(f"Rate limit hit for user {user.id}")
            await event.answer(
                f"⏳ Слишком много запросов. Подождите {settings.rate_limit_window} секунд.",
                parse_mode=None,
            )
            return None

        timestamps.append(now)
        return await handler(event, data)
