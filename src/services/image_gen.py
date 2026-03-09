import asyncio
import logging

from google import genai
from google.genai import types

from config.settings import settings

logger = logging.getLogger(__name__)

client: genai.Client | None = None


def init_image_client() -> None:
    """Initialize Google GenAI client for image generation."""
    global client
    if settings.gemini_api_key:
        client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"Google GenAI client initialized ({settings.image_model})")
    else:
        logger.warning("GEMINI_API_KEY not set, image generation disabled")


def get_image_client() -> genai.Client | None:
    """Get Google GenAI client."""
    return client


async def generate_image(prompt: str) -> tuple[bytes, str] | str:
    """
    Generate image using Nano Banana (Gemini 3.1 Flash Image).

    Args:
        prompt: Text description of the image to generate

    Returns:
        Tuple of (image_bytes, mime_type) or error message string
    """
    if client is None:
        logger.error("Client is None")
        return "Генерация изображений не настроена"

    logger.info(f"Calling Nano Banana API with prompt: {prompt[:50]}...")
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.image_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        return _extract_image(response)

    except Exception as e:
        return _handle_error(e)


async def edit_image(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> tuple[bytes, str] | str:
    """
    Edit image using Nano Banana.

    Args:
        prompt: Text description of desired edits
        image_bytes: Source image bytes
        mime_type: Source image MIME type

    Returns:
        Tuple of (image_bytes, mime_type) or error message string
    """
    if client is None:
        logger.error("Client is None")
        return "Генерация изображений не настроена"

    logger.info(f"Calling Nano Banana edit with prompt: {prompt[:50]}...")
    try:
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.image_model,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        return _extract_image(response)

    except Exception as e:
        return _handle_error(e)


def _extract_image(response: types.GenerateContentResponse) -> tuple[bytes, str] | str:
    """Extract image bytes from Gemini response."""
    if response.candidates and response.candidates[0].content:
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                image_bytes = part.inline_data.data
                result_mime = part.inline_data.mime_type or "image/png"
                logger.info(f"Image generated successfully: {len(image_bytes)} bytes")
                return (image_bytes, result_mime)

    return "Не удалось сгенерировать изображение"


def _handle_error(e: Exception) -> str:
    """Handle image generation errors."""
    error_msg = str(e)
    logger.error(f"Image generation error: {error_msg}")

    if "PERMISSION_DENIED" in error_msg or "403" in error_msg:
        return "Генерация изображений недоступна на бесплатном тарифе Google AI."
    elif "billed users" in error_msg.lower() or "billing" in error_msg.lower():
        return "API доступен только для платных аккаунтов Google AI."
    elif "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
        return "Превышен лимит запросов. Попробуйте позже."
    elif "NOT_FOUND" in error_msg or "404" in error_msg:
        return "Модель генерации изображений недоступна"
    elif "INVALID_ARGUMENT" in error_msg:
        return "Некорректный запрос. Попробуйте изменить описание."
    elif "safety" in error_msg.lower() or "blocked" in error_msg.lower():
        return "Запрос заблокирован фильтром безопасности. Попробуйте изменить описание."

    return "Ошибка генерации изображения"
