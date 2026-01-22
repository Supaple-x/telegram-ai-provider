import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from src.database.context import ensure_user, clear_context

logger = logging.getLogger(__name__)
router = Router()

WELCOME_MESSAGE = """👋 Привет! Я AI-ассистент на базе Claude.

**Что я умею:**
• Отвечать на вопросы и вести диалог
• Анализировать изображения — просто пришли фото
• Читать документы — PDF, DOCX, TXT

**Команды:**
/clear — очистить контекст диалога
/help — показать эту справку

Просто напиши мне сообщение! 💬"""


def get_clear_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard with clear context button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Очистить контекст", callback_data="clear_context")]
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(WELCOME_MESSAGE, parse_mode="Markdown")
    logger.info(f"User {message.from_user.id} started bot")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(WELCOME_MESSAGE, parse_mode="Markdown")


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    """Handle /clear command."""
    count = await clear_context(message.from_user.id)
    await message.answer(f"✅ Контекст очищен ({count} сообщений удалено)")


@router.callback_query(lambda c: c.data == "clear_context")
async def callback_clear_context(callback: CallbackQuery) -> None:
    """Handle clear context button click."""
    count = await clear_context(callback.from_user.id)
    await callback.answer(f"Контекст очищен ({count} сообщений)")
    await callback.message.edit_reply_markup(reply_markup=None)
