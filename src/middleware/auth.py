import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
)

from config.settings import settings
from src.database.allowed_users import is_approved

logger = logging.getLogger(__name__)

# ReplyKeyboard with "Share contact" button
_CONTACT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Поделиться контактом", request_contact=True)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


class AuthMiddleware(BaseMiddleware):
    """Middleware that restricts bot access to allowed users only.

    Supports:
    - Numeric Telegram IDs and usernames in ALLOWED_USERS env var
    - Self-registration via contact sharing (DB-backed cache)
    - If ALLOWED_USERS is empty, access is unrestricted.
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

        # Check by numeric ID (env)
        if str(user.id) in settings.allowed_users:
            return await handler(event, data)

        # Check by username (env, case-insensitive)
        if user.username and user.username.lower() in settings.allowed_users_lower:
            return await handler(event, data)

        # Check DB-approved users (in-memory cache)
        if is_approved(user.id):
            return await handler(event, data)

        # Let contact messages through for the registration handler
        if isinstance(event, Message) and event.contact is not None:
            return await handler(event, data)

        # Unauthorized
        logger.warning(
            f"Unauthorized access attempt: user_id={user.id}, username=@{user.username}"
        )

        if isinstance(event, Message):
            await event.answer(
                "🔒 Бот доступен только для авторизованных пользователей.\n\n"
                "Для получения доступа нажмите кнопку ниже и поделитесь "
                "своим контактным номером.",
                parse_mode=None,
                reply_markup=_CONTACT_KEYBOARD,
            )
        elif isinstance(event, CallbackQuery):
            await event.answer("🔒 Доступ запрещён.", show_alert=True)

        return None
