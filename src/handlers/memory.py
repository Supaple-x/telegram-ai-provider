import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.database.context import ensure_user
from src.database.memory import (
    get_memories,
    add_memory,
    remove_memory,
    clear_memories,
    MAX_MEMORIES_PER_USER,
)

logger = logging.getLogger(__name__)
router = Router()


def _build_memory_list(
    memories: list[dict],
    header: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build formatted memory list text and keyboard with delete buttons.

    Args:
        memories: List of memory dicts with 'id' and 'content' keys
        header: Header line for the message

    Returns:
        Tuple of (formatted text, inline keyboard)
    """
    lines = [header]
    buttons = []

    for i, mem in enumerate(memories, 1):
        lines.append(f"{i}. {mem['content']}")
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 {i}. {mem['content'][:30]}{'...' if len(mem['content']) > 30 else ''}",
                callback_data=f"forget_{mem['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="🗑 Очистить всё", callback_data="forget_all")
    ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("remember"))
async def cmd_remember(message: Message) -> None:
    """Handle /remember <text> — save a memory."""
    await ensure_user(message.from_user.id, message.from_user.username)

    text = message.text.removeprefix("/remember").strip()
    if not text:
        await message.answer(
            "Использование: `/remember <факт>`\n\n"
            "Примеры:\n"
            "• `/remember Меня зовут Алексей`\n"
            "• `/remember Я Python-разработчик`\n"
            "• `/remember Предпочитаю краткие ответы`",
            parse_mode="Markdown",
        )
        return

    if len(text) > 500:
        await message.answer("⚠️ Максимальная длина записи — 500 символов.", parse_mode=None)
        return

    result = await add_memory(message.from_user.id, text)

    if result == "ok":
        await message.answer(f"✅ Запомнил: _{text}_", parse_mode="Markdown")
    elif result == "duplicate":
        await message.answer("ℹ️ Это уже есть в памяти.", parse_mode=None)
    elif result == "limit":
        await message.answer(
            f"⚠️ Достигнут лимит ({MAX_MEMORIES_PER_USER} записей). "
            "Удалите ненужные через /memories.",
            parse_mode=None,
        )


@router.message(Command("memories"))
async def cmd_memories(message: Message) -> None:
    """Handle /memories — list all memories."""
    await ensure_user(message.from_user.id, message.from_user.username)

    memories = await get_memories(message.from_user.id)

    if not memories:
        await message.answer(
            "🧠 Память пуста.\n\nИспользуйте `/remember <факт>` чтобы сохранить информацию.",
            parse_mode="Markdown",
        )
        return

    header = f"🧠 **Память** ({len(memories)}/{MAX_MEMORIES_PER_USER}):\n"
    text, keyboard = _build_memory_list(memories, header)
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.message(Command("forget"))
async def cmd_forget(message: Message) -> None:
    """Handle /forget — show memories list for deletion."""
    await ensure_user(message.from_user.id, message.from_user.username)

    memories = await get_memories(message.from_user.id)

    if not memories:
        await message.answer("🧠 Память уже пуста.", parse_mode=None)
        return

    text, keyboard = _build_memory_list(memories, "Выберите запись для удаления:\n")
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


@router.callback_query(lambda c: c.data and c.data.startswith("forget_"))
async def callback_forget(callback: CallbackQuery) -> None:
    """Handle memory deletion via inline buttons."""
    data = callback.data

    if data == "forget_all":
        count = await clear_memories(callback.from_user.id)
        await callback.answer(f"Удалено записей: {count}")
        await callback.message.edit_text("🧠 Память очищена.", reply_markup=None)
        return

    # Extract memory ID: forget_123
    try:
        memory_id = int(data.removeprefix("forget_"))
    except ValueError:
        await callback.answer("Ошибка: неверный ID")
        return

    deleted = await remove_memory(callback.from_user.id, memory_id)

    if deleted:
        await callback.answer("Запись удалена")
        # Refresh the list
        memories = await get_memories(callback.from_user.id)
        if not memories:
            await callback.message.edit_text("🧠 Память пуста.", reply_markup=None)
            return

        header = f"🧠 **Память** ({len(memories)}/{MAX_MEMORIES_PER_USER}):\n"
        text, keyboard = _build_memory_list(memories, header)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await callback.answer("Запись не найдена")
