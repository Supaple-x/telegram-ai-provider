"""Handler for contact-based self-registration."""

import logging

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from src.database.allowed_users import approve_user, is_approved

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.contact)
async def handle_contact(message: Message) -> None:
    """Handle shared contact for self-registration."""
    contact = message.contact
    user_id = message.from_user.id

    # Already approved — just confirm
    if is_approved(user_id):
        await message.answer(
            "✅ У вас уже есть доступ к боту! Напишите любое сообщение.",
            parse_mode=None,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Verify it's the user's own contact
    if contact.user_id != user_id:
        logger.warning(
            f"User {user_id} sent someone else's contact (contact.user_id={contact.user_id})"
        )
        await message.answer(
            "⚠️ Пожалуйста, отправьте *свой* контактный номер, "
            "нажав кнопку «📱 Поделиться контактом».\n\n"
            "Чужие контакты не принимаются.",
            parse_mode="Markdown",
        )
        return

    # Approve user
    phone = contact.phone_number
    username = message.from_user.username

    await approve_user(user_id, phone, username)

    logger.info(f"New user approved via contact: {user_id} (@{username}, {phone})")

    await message.answer(
        "✅ Доступ предоставлен! Добро пожаловать.\n\n"
        "Напишите /help чтобы узнать, что я умею.",
        parse_mode=None,
        reply_markup=ReplyKeyboardRemove(),
    )
