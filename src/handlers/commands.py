import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config.settings import settings
from src.database.context import ensure_user, clear_context, get_stats
from src.database.preferences import get_preferred_model, set_preferred_model

logger = logging.getLogger(__name__)
router = Router()

WELCOME_MESSAGE = """👋 Привет! Я AI-ассистент на базе Claude.

**Что я умею:**
• Отвечать на вопросы и вести диалог
• Анализировать изображения — просто пришли фото
• Читать документы — PDF, DOCX, TXT
• Распознавать голосовые сообщения
• Искать в интернете — /search
• Генерировать изображения — /imagine
• Генерировать видео — /video
• Запоминать важные факты — /remember

**Команды:**
/search — поиск в интернете
/imagine — сгенерировать изображение
/video — сгенерировать видео
/remember — запомнить факт
/memories — список запомненного
/forget — забыть факт
/model — переключить модель AI
/clear — очистить контекст диалога
/stats — статистика бота
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


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Handle /stats command. Shows bot statistics."""
    stats = await get_stats()
    text = (
        f"📊 Статистика бота\n\n"
        f"👥 Пользователей: {stats['users_total']}\n"
        f"💬 Сообщений в БД: {stats['messages_total']}\n"
        f"🟢 Активны сегодня: {stats['active_today']}\n"
        f"\n"
        f"⚙️ Модель: {settings.claude_model}\n"
        f"🔄 Fallback: {settings.openai_model}\n"
        f"📝 Контекст: {settings.max_context_messages} сообщений\n"
        f"🔒 Доступ: {'ограничен' if settings.allowed_users else 'открыт'}"
    )
    await message.answer(text, parse_mode=None)


@router.callback_query(lambda c: c.data == "clear_context")
async def callback_clear_context(callback: CallbackQuery) -> None:
    """Handle clear context button click."""
    count = await clear_context(callback.from_user.id)
    await callback.answer(f"Контекст очищен ({count} сообщений)")
    await callback.message.edit_reply_markup(reply_markup=None)


# --- Model switching ---

MODEL_NAMES = {
    "claude": f"Claude ({settings.claude_model})",
    "openai": f"GPT-5.2 ({settings.openai_model})",
}


def _model_keyboard(current: str) -> InlineKeyboardMarkup:
    """Build inline keyboard with model choices. Current model gets a green dot."""
    buttons = []
    for key, label in MODEL_NAMES.items():
        prefix = "🟢 " if key == current else "⚪ "
        buttons.append(
            InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"model_{key}")
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@router.message(Command("model"))
async def cmd_model(message: Message) -> None:
    """Handle /model command — show current model and switch buttons."""
    await ensure_user(message.from_user.id, message.from_user.username)
    current = await get_preferred_model(message.from_user.id)
    await message.answer(
        f"⚙️ Текущая модель: **{MODEL_NAMES[current]}**\n\n"
        f"Выберите модель для ответов:",
        parse_mode="Markdown",
        reply_markup=_model_keyboard(current),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("model_"))
async def callback_model_switch(callback: CallbackQuery) -> None:
    """Handle model switch button press."""
    model = callback.data.removeprefix("model_")
    if model not in MODEL_NAMES:
        await callback.answer("Неизвестная модель", show_alert=True)
        return

    current = await get_preferred_model(callback.from_user.id)
    if model == current:
        await callback.answer(f"Уже используется {MODEL_NAMES[model]}")
        return

    await set_preferred_model(callback.from_user.id, model)
    await callback.answer(f"Переключено на {MODEL_NAMES[model]}")
    await callback.message.edit_text(
        f"✅ Модель переключена на **{MODEL_NAMES[model]}**\n\n"
        f"Все ответы будут генерироваться через эту модель.\n"
        f"Переключить обратно: /model",
        parse_mode="Markdown",
        reply_markup=None,
    )
