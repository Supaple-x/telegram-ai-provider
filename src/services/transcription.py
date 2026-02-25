import io
import logging

from openai import AsyncOpenAI
from config.settings import settings

logger = logging.getLogger(__name__)

client: AsyncOpenAI | None = None


def init_transcription_client() -> None:
    """Initialize transcription client (reuses OpenAI client)."""
    global client
    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        logger.info(f"Transcription client initialized ({settings.whisper_model})")
    else:
        logger.warning("OPENAI_API_KEY not set, voice transcription disabled")


def get_transcription_client() -> AsyncOpenAI | None:
    """Get transcription client."""
    return client


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Transcribe audio using OpenAI Whisper API.

    Args:
        audio_bytes: Raw audio file bytes
        filename: Original filename (helps API detect format)

    Returns:
        Transcribed text or error message
    """
    if client is None:
        return "❌ Транскрипция не настроена (нет OpenAI API ключа)."

    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        response = await client.audio.transcriptions.create(
            model=settings.whisper_model,
            file=audio_file,
            language="ru",
        )

        text = response.text.strip()
        if not text:
            return "❌ Не удалось распознать речь. Попробуйте ещё раз."

        logger.info(f"Transcribed {len(audio_bytes)} bytes -> {len(text)} chars")
        return text

    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        return "❌ Ошибка при распознавании речи. Попробуйте позже."
