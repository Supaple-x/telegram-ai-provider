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
    Generate image using Imagen 4.

    Args:
        prompt: Text description of the image to generate

    Returns:
        Tuple of (image_bytes, mime_type) or error message string
    """
    if client is None:
        logger.error("Client is None")
        return "Генерация изображений не настроена"

    logger.info(f"Calling Imagen 4 API with prompt: {prompt[:50]}...")
    try:
        response = await asyncio.to_thread(
            client.models.generate_images,
            model=settings.image_model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
                safety_filter_level="BLOCK_LOW_AND_ABOVE",
            ),
        )

        if response.generated_images:
            image = response.generated_images[0]
            image_bytes = image.image.image_bytes
            mime_type = "image/png"

            logger.info(f"Image generated successfully: {len(image_bytes)} bytes")
            return (image_bytes, mime_type)

        return "Не удалось сгенерировать изображение"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image generation error: {error_msg}")

        if "PERMISSION_DENIED" in error_msg or "403" in error_msg:
            return "Imagen недоступен на бесплатном тарифе. Требуется платная подписка Google AI."
        elif "billed users" in error_msg.lower() or "billing" in error_msg.lower():
            return "Imagen API доступен только для платных аккаунтов Google AI."
        elif "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
            return "Превышен лимит запросов. Попробуйте позже."
        elif "NOT_FOUND" in error_msg or "404" in error_msg:
            return "Модель генерации изображений недоступна"
        elif "INVALID_ARGUMENT" in error_msg:
            return "Некорректный запрос. Попробуйте изменить описание."

        return "Ошибка генерации изображения"


async def edit_image(
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> tuple[bytes, str] | str:
    """
    Edit image - currently not supported on free tier.
    """
    return "Редактирование изображений недоступно на текущем тарифе"
