import asyncio
import base64
import logging
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from src.database.context import ensure_user, get_context, add_message
from src.database.memory import get_memory_texts
from src.database.preferences import get_preferred_model
from src.services.claude import generate_response_stream, build_system_prompt, FallbackError
from src.services.openai_fallback import (
    generate_openai_response_stream,
    get_openai_client,
)
from src.services.documents import process_document
from src.utils.text import split_message
from src.handlers.commands import get_clear_keyboard

logger = logging.getLogger(__name__)
router = Router()

FALLBACK_PREFIX = "FALLBACK:"
STREAM_CURSOR = " ▍"

# Per-user locks to prevent race conditions on concurrent messages
_user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def keep_typing(bot: Bot, chat_id: int) -> AsyncGenerator[None, None]:
    """Send typing indicator every 4 seconds until the block exits."""
    stop = asyncio.Event()

    async def _typing_loop() -> None:
        while not stop.is_set():
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_typing_loop())
    try:
        yield
    finally:
        stop.set()
        await task


def get_fallback_keyboard() -> InlineKeyboardMarkup:
    """Create inline keyboard with GPT-5.2 fallback button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Отправить в GPT-5.2", callback_data="fallback_gpt")],
    ])


async def download_file(bot: Bot, file_id: str) -> bytes:
    """Download file from Telegram."""
    file = await bot.get_file(file_id)
    file_bytes = await bot.download_file(file.file_path)
    return file_bytes.read()


async def _safe_edit(msg: Message, text: str, **kwargs) -> bool:
    """Edit message, returning False if content didn't change."""
    try:
        await msg.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest:
        return False


async def stream_to_message(
    message: Message,
    stream: AsyncGenerator[str, None],
    bot: Bot,
    suffix: str = "",
) -> str:
    """Stream AI response into a Telegram message, editing it progressively.

    Args:
        message: The user's message to reply to
        stream: Async generator yielding text chunks
        bot: Bot instance
        suffix: Text to append after the final message (e.g. "_via GPT-5.2_")

    Returns:
        Full accumulated response text
    """
    accumulated = ""
    sent_msg: Message | None = None
    last_edit = 0.0
    edit_interval = settings.stream_edit_interval
    messages_sent: list[Message] = []

    async for chunk in stream:
        accumulated += chunk
        now = time.monotonic()

        if sent_msg is None:
            # Send first message with cursor
            sent_msg = await message.answer(accumulated + STREAM_CURSOR, parse_mode=None)
            messages_sent.append(sent_msg)
            last_edit = now
            continue

        # Check if we need to split (approaching Telegram 4096 limit)
        if len(accumulated) > 3800 and now - last_edit >= edit_interval:
            # Find a good split point
            split_at = accumulated.rfind("\n\n", 3000, 3800)
            if split_at == -1:
                split_at = accumulated.rfind("\n", 3000, 3800)
            if split_at == -1:
                split_at = 3800

            # Finalize current message (without cursor)
            first_part = accumulated[:split_at]
            await _safe_edit(sent_msg, first_part, parse_mode=None)

            # Start new message with remainder
            accumulated = accumulated[split_at:].lstrip("\n")
            sent_msg = await message.answer(accumulated + STREAM_CURSOR, parse_mode=None)
            messages_sent.append(sent_msg)
            last_edit = now
            continue

        # Regular edit at interval
        if now - last_edit >= edit_interval:
            await _safe_edit(sent_msg, accumulated + STREAM_CURSOR, parse_mode=None)
            last_edit = now

    # Final edit — try Markdown formatting
    if sent_msg and accumulated:
        final_text = accumulated + suffix
        # Try Markdown first
        try:
            await sent_msg.edit_text(
                final_text,
                parse_mode="Markdown",
                reply_markup=get_clear_keyboard(),
            )
        except TelegramBadRequest:
            # Fallback to plain text
            await _safe_edit(
                sent_msg,
                final_text,
                parse_mode=None,
                reply_markup=get_clear_keyboard(),
            )

    return accumulated


async def send_fallback_offer(message: Message, error_text: str) -> None:
    """Show fallback button when Claude is unavailable."""
    if get_openai_client():
        await message.answer(
            f"{error_text}\n\nМогу отправить ваш запрос в GPT-5.2 (OpenAI).",
            reply_markup=get_fallback_keyboard(),
            parse_mode=None,
        )
    else:
        await message.answer(
            f"{error_text}\nПопробуйте позже.",
            parse_mode=None,
        )


async def handle_ai_response(
    message: Message,
    bot: Bot,
    user_id: int,
    context: list[dict],
    system_prompt: str,
    preferred_model: str,
    image_data: tuple[str, str] | None = None,
) -> None:
    """Route to AI model based on preference, stream response, save to DB.

    Handles FallbackError internally by offering GPT-5.2 fallback.
    """
    if preferred_model == "openai":
        stream = generate_openai_response_stream(
            context, image_data=image_data, system_prompt=system_prompt,
        )
        response = await stream_to_message(message, stream, bot, suffix="\n\n_GPT-5.2_")
    else:
        try:
            stream = generate_response_stream(
                context, image_data=image_data, system_prompt=system_prompt,
            )
            response = await stream_to_message(message, stream, bot)
        except FallbackError as e:
            await send_fallback_offer(message, str(e))
            return

    if response:
        await add_message(user_id, "assistant", response)


@router.callback_query(F.data == "fallback_gpt")
async def handle_fallback_callback(callback: CallbackQuery, bot: Bot) -> None:
    """Handle GPT-5.2 fallback button press."""
    await callback.answer("Отправляю в GPT-5.2...")

    user_id = callback.from_user.id
    message = callback.message

    # Get context
    context = await get_context(user_id)
    if not context:
        await message.answer("❌ Контекст пуст. Отправьте сообщение заново.", parse_mode=None)
        return

    # Remove the error message
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    # Stream response via OpenAI
    stream = generate_openai_response_stream(context)
    response = await stream_to_message(
        callback.message, stream, bot, suffix="\n\n_via GPT-5.2_"
    )

    # Save assistant response
    if response:
        await add_message(user_id, "assistant", response)


@router.message(lambda m: m.photo)
async def handle_photo(message: Message, bot: Bot) -> None:
    """Handle photo messages (vision)."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    async with _user_locks[user_id]:
        try:
            # Get the largest photo
            photo = message.photo[-1]
            file_bytes = await download_file(bot, photo.file_id)

            # Convert to base64
            base64_data = base64.b64encode(file_bytes).decode("utf-8")
            media_type = "image/jpeg"

            # Get user's caption or default question
            user_text = message.caption or "Что на этом изображении?"

            # Get context, memories, and preference in parallel
            context, memories, preferred = await asyncio.gather(
                get_context(user_id),
                get_memory_texts(user_id),
                get_preferred_model(user_id),
            )
            await add_message(user_id, "user", f"[Изображение] {user_text}",
                              image_data=(base64_data, media_type))
            context.append({"role": "user", "content": user_text})

            # Stream response with image
            system_prompt = build_system_prompt(memories)
            await handle_ai_response(
                message, bot, user_id, context, system_prompt, preferred,
                image_data=(base64_data, media_type),
            )

        except asyncpg.PostgresError as e:
            logger.error(f"Database error processing photo: {e}")
            await message.answer("❌ Ошибка базы данных. Попробуйте позже.", parse_mode=None)
        except TelegramBadRequest as e:
            logger.error(f"Telegram error processing photo: {e}")
            await message.answer("❌ Ошибка отправки ответа.", parse_mode=None)
        except Exception as e:
            logger.error(f"Error processing photo: {e}", exc_info=True)
            await message.answer("❌ Ошибка при обработке изображения. Попробуйте ещё раз.", parse_mode=None)


@router.message(lambda m: m.document)
async def handle_document(message: Message, bot: Bot) -> None:
    """Handle document messages (PDF, DOCX, TXT)."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    async with _user_locks[user_id]:
        try:
            doc = message.document
            filename = doc.file_name or "document"

            # Check file size (20MB limit)
            if doc.file_size > 20 * 1024 * 1024:
                await message.answer("⚠️ Файл слишком большой. Максимум 20 МБ.", parse_mode=None)
                return

            # Download and process document
            file_bytes = await download_file(bot, doc.file_id)
            extracted_text = await process_document(file_bytes, filename)

            if extracted_text.startswith("❌") or extracted_text.startswith("⚠️"):
                await message.answer(extracted_text, parse_mode=None)
                return

            # Wrap document content in XML tags (prompt injection protection)
            user_text = message.caption or "Проанализируй этот документ"
            full_message = (
                f"{user_text}\n\n"
                f"<document name=\"{filename}\">\n{extracted_text}\n</document>"
            )

            # Get context, memories, and preference in parallel
            context, memories, preferred = await asyncio.gather(
                get_context(user_id),
                get_memory_texts(user_id),
                get_preferred_model(user_id),
            )
            await add_message(user_id, "user", f"[Документ: {filename}] {user_text}")
            context.append({"role": "user", "content": full_message})

            # Stream response
            system_prompt = build_system_prompt(memories)
            await handle_ai_response(
                message, bot, user_id, context, system_prompt, preferred,
            )

        except asyncpg.PostgresError as e:
            logger.error(f"Database error processing document: {e}")
            await message.answer("❌ Ошибка базы данных. Попробуйте позже.", parse_mode=None)
        except TelegramBadRequest as e:
            logger.error(f"Telegram error processing document: {e}")
            await message.answer("❌ Ошибка отправки ответа.", parse_mode=None)
        except Exception as e:
            logger.error(f"Error processing document: {e}", exc_info=True)
            await message.answer("❌ Ошибка при обработке документа. Попробуйте ещё раз.", parse_mode=None)


@router.message(lambda m: m.text)
async def handle_text(message: Message, bot: Bot) -> None:
    """Handle text messages."""
    user_id = message.from_user.id
    user_text = message.text

    await ensure_user(user_id, message.from_user.username)

    async with _user_locks[user_id]:
        try:
            # Get context, memories, and preference in parallel
            context, memories, preferred = await asyncio.gather(
                get_context(user_id),
                get_memory_texts(user_id),
                get_preferred_model(user_id),
            )
            await add_message(user_id, "user", user_text)
            context.append({"role": "user", "content": user_text})

            # Stream response
            system_prompt = build_system_prompt(memories)
            await handle_ai_response(
                message, bot, user_id, context, system_prompt, preferred,
            )

        except asyncpg.PostgresError as e:
            logger.error(f"Database error processing message: {e}")
            await message.answer("❌ Ошибка базы данных. Попробуйте позже.", parse_mode=None)
        except TelegramBadRequest as e:
            logger.error(f"Telegram error processing message: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.", parse_mode=None)
