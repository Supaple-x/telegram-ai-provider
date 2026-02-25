import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from config.settings import settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Middleware that restricts bot access to allowed users only.

    Supports both numeric Telegram IDs and usernames in ALLOWED_USERS.
    If ALLOWED_USERS is empty, access is unrestricted.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # No restrictions if list is empty
        if not settings.allowed_users:
            return await handler(event, data)

        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Check by numeric ID
        if str(user.id) in settings.allowed_users:
            return await handler(event, data)

        # Check by username (case-insensitive)
        if user.username and user.username.lower() in settings.allowed_users_lower:
            return await handler(event, data)

        # Unauthorized
        logger.warning(
            f"Unauthorized access attempt: user_id={user.id}, username=@{user.username}"
        )

        if isinstance(event, Message):
            await event.answer(
                "🔒 Бот доступен только для авторизованных пользователей.\n"
                "Обратитесь к администратору для получения доступа.",
                parse_mode=None,
            )
        elif isinstance(event, CallbackQuery):
            await event.answer("🔒 Доступ запрещён.", show_alert=True)

        return None
