import asyncio
import logging

import asyncpg
from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from src.database.context import ensure_user, get_context, add_message
from src.database.memory import get_memory_texts
from src.database.preferences import get_preferred_model
from src.services.claude import build_system_prompt
from src.services.transcription import get_transcription_client, transcribe_audio
from src.handlers.messages import download_file, handle_ai_response, _user_locks

logger = logging.getLogger(__name__)
router = Router()

# Max voice file size: 20MB
MAX_VOICE_SIZE = 20 * 1024 * 1024


async def _process_audio_message(
    message: Message,
    bot: Bot,
    *,
    file_id: str,
    file_size: int | None,
    filename: str,
    status_text: str,
    size_error: str,
    error_label: str,
    db_prefix: str = "",
    use_caption: bool = False,
) -> None:
    """Common logic for voice and audio message handling.

    Args:
        file_id: Telegram file ID to download
        file_size: File size in bytes (for limit check)
        filename: Filename hint for transcription API
        status_text: Status message shown during transcription
        size_error: Error message if file is too large
        error_label: Label for log messages (e.g. "voice", "audio")
        db_prefix: Prefix for DB message content (e.g. "[Аудио] ")
        use_caption: Whether to prefer message.caption over transcribed text
    """
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    if not get_transcription_client():
        await message.answer(
            "❌ Голосовые сообщения не поддерживаются (OpenAI API не настроен).",
            parse_mode=None,
        )
        return

    async with _user_locks[user_id]:
        try:
            if file_size and file_size > MAX_VOICE_SIZE:
                await message.answer(size_error, parse_mode=None)
                return

            # Download and transcribe
            file_bytes = await download_file(bot, file_id)

            status_msg = await message.answer(status_text, parse_mode=None)
            transcribed_text = await transcribe_audio(file_bytes, filename)

            try:
                await status_msg.delete()
            except TelegramBadRequest:
                pass

            if transcribed_text.startswith("❌"):
                await message.answer(transcribed_text, parse_mode=None)
                return

            # Show transcription preview
            preview = transcribed_text[:200]
            if len(transcribed_text) > 200:
                preview += "..."
            await message.answer(f"🎤 _{preview}_", parse_mode="Markdown")

            # Build context and send to AI
            user_text = (message.caption or transcribed_text) if use_caption else transcribed_text
            db_content = f"{db_prefix}{user_text}" if db_prefix else user_text

            context, memories, preferred = await asyncio.gather(
                get_context(user_id),
                get_memory_texts(user_id),
                get_preferred_model(user_id),
            )
            await add_message(user_id, "user", db_content)
            context.append({"role": "user", "content": user_text})

            system_prompt = build_system_prompt(memories)
            await handle_ai_response(
                message, bot, user_id, context, system_prompt, preferred,
            )

        except asyncpg.PostgresError as e:
            logger.error(f"Database error processing {error_label}: {e}")
            await message.answer("❌ Ошибка базы данных. Попробуйте позже.", parse_mode=None)
        except TelegramBadRequest as e:
            logger.error(f"Telegram error processing {error_label}: {e}")
            await message.answer("❌ Ошибка отправки ответа.", parse_mode=None)
        except Exception as e:
            logger.error(f"Error processing {error_label}: {e}", exc_info=True)
            await message.answer(
                f"❌ Ошибка при обработке {error_label}. Попробуйте ещё раз.",
                parse_mode=None,
            )


@router.message(lambda m: m.voice)
async def handle_voice(message: Message, bot: Bot) -> None:
    """Handle voice messages — transcribe and send to AI."""
    voice = message.voice
    await _process_audio_message(
        message, bot,
        file_id=voice.file_id,
        file_size=voice.file_size,
        filename="voice.ogg",
        status_text="🎤 Распознаю речь...",
        size_error="⚠️ Голосовое сообщение слишком большое. Максимум 20 МБ.",
        error_label="голосового сообщения",
    )


@router.message(lambda m: m.audio)
async def handle_audio(message: Message, bot: Bot) -> None:
    """Handle audio files — transcribe and send to AI."""
    audio = message.audio
    await _process_audio_message(
        message, bot,
        file_id=audio.file_id,
        file_size=audio.file_size,
        filename=audio.file_name or "audio.mp3",
        status_text="🎤 Распознаю аудио...",
        size_error="⚠️ Аудиофайл слишком большой. Максимум 20 МБ.",
        error_label="аудиофайла",
        db_prefix="[Аудио] ",
        use_caption=True,
    )
