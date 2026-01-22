import base64
import logging
from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.enums import ChatAction

from config.settings import settings
from src.database.context import ensure_user, get_context, add_message
from src.services.claude import generate_response
from src.services.documents import process_document
from src.utils.text import split_message
from src.handlers.commands import get_clear_keyboard

logger = logging.getLogger(__name__)
router = Router()


async def download_file(bot: Bot, file_id: str) -> bytes:
    """Download file from Telegram."""
    file = await bot.get_file(file_id)
    file_bytes = await bot.download_file(file.file_path)
    return file_bytes.read()


@router.message(lambda m: m.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    """Handle photo messages (vision)."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    # Show typing indicator
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        # Get the largest photo
        photo = message.photo[-1]
        file_bytes = await download_file(bot, photo.file_id)

        # Convert to base64
        base64_data = base64.b64encode(file_bytes).decode("utf-8")
        media_type = "image/jpeg"

        # Get user's caption or default question
        user_text = message.caption or "Что на этом изображении?"

        # Get context and add user message
        context = await get_context(user_id)
        await add_message(user_id, "user", f"[Изображение] {user_text}")
        context.append({"role": "user", "content": user_text})

        # Generate response with image
        response = await generate_response(context, image_data=(base64_data, media_type))

        # Save assistant response
        await add_message(user_id, "assistant", response)

        # Send response (split if needed)
        parts = split_message(response)
        for i, part in enumerate(parts):
            # Add clear button only to last message
            reply_markup = get_clear_keyboard() if i == len(parts) - 1 else None
            await message.answer(part, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await message.answer("❌ Ошибка при обработке изображения. Попробуйте ещё раз.")


@router.message(lambda m: m.document)
async def handle_document(message: Message, bot: Bot) -> None:
    """Handle document messages (PDF, DOCX, TXT)."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    # Show typing indicator
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        doc = message.document
        filename = doc.file_name or "document"

        # Check file size (20MB limit)
        if doc.file_size > 20 * 1024 * 1024:
            await message.answer("⚠️ Файл слишком большой. Максимум 20 МБ.")
            return

        # Download and process document
        file_bytes = await download_file(bot, doc.file_id)
        extracted_text = await process_document(file_bytes, filename)

        if extracted_text.startswith("❌") or extracted_text.startswith("⚠️"):
            await message.answer(extracted_text)
            return

        # Build user message with document content
        user_text = message.caption or "Проанализируй этот документ"
        full_message = f"{user_text}\n\n📄 Содержимое документа '{filename}':\n{extracted_text}"

        # Get context and add user message
        context = await get_context(user_id)
        await add_message(user_id, "user", f"[Документ: {filename}] {user_text}")
        context.append({"role": "user", "content": full_message})

        # Generate response
        response = await generate_response(context)

        # Save assistant response
        await add_message(user_id, "assistant", response)

        # Send response
        parts = split_message(response)
        for i, part in enumerate(parts):
            reply_markup = get_clear_keyboard() if i == len(parts) - 1 else None
            await message.answer(part, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await message.answer("❌ Ошибка при обработке документа. Попробуйте ещё раз.")


@router.message(lambda m: m.text)
async def handle_text(message: Message, bot: Bot) -> None:
    """Handle text messages."""
    user_id = message.from_user.id
    user_text = message.text

    await ensure_user(user_id, message.from_user.username)

    # Show typing indicator
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    try:
        # Get context and add user message
        context = await get_context(user_id)
        await add_message(user_id, "user", user_text)
        context.append({"role": "user", "content": user_text})

        # Generate response
        response = await generate_response(context)

        # Save assistant response
        await add_message(user_id, "assistant", response)

        # Send response (split if needed)
        parts = split_message(response)
        for i, part in enumerate(parts):
            reply_markup = get_clear_keyboard() if i == len(parts) - 1 else None
            await message.answer(part, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")
