import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI
from config.settings import settings
from config.prompts import OPENAI_SYSTEM_PROMPT as SYSTEM_PROMPT

logger = logging.getLogger(__name__)

client: AsyncOpenAI | None = None


def init_openai_client() -> None:
    """Initialize OpenAI client."""
    global client
    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        logger.info(f"OpenAI client initialized ({settings.openai_model})")
    else:
        logger.warning("OPENAI_API_KEY not set, fallback disabled")


def get_openai_client() -> AsyncOpenAI | None:
    """Get OpenAI client."""
    return client


def _build_openai_messages(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
    system_prompt: str | None = None,
) -> list[dict]:
    """Build OpenAI API messages from conversation history.

    Supports images in any message position (from stored context) and an
    explicit image_data parameter for the current (last) message.
    """
    api_messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]

    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        msg_image = image_data if (is_last and image_data) else msg.get("image_data")

        if msg_image:
            b64_data, m_type = msg_image
            content = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{m_type};base64,{b64_data}"},
                },
                {"type": "text", "text": msg["content"] or "Что на этом изображении?"},
            ]
            api_messages.append({"role": msg["role"], "content": content})
        else:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    return api_messages


async def generate_openai_response(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
    system_prompt: str | None = None,
) -> str:
    """Generate response from OpenAI GPT-5.2."""
    if client is None:
        return "❌ Резервная модель (OpenAI) не настроена."

    api_messages = _build_openai_messages(messages, image_data, system_prompt)

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=settings.max_tokens,
            messages=api_messages,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"OpenAI API error: {e}", exc_info=True)
        return "❌ Ошибка при обращении к резервной модели (GPT-5.2). Попробуйте позже."


async def generate_openai_response_stream(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream response from OpenAI GPT-5.2, yielding text chunks."""
    if client is None:
        logger.error("OpenAI client not initialized, cannot stream")
        yield "❌ Резервная модель (OpenAI) не настроена."
        return

    api_messages = _build_openai_messages(messages, image_data, system_prompt)

    try:
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=settings.max_tokens,
            messages=api_messages,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    except Exception as e:
        logger.error(f"OpenAI streaming error: {e}", exc_info=True)
        yield "\n\n❌ Ошибка при обращении к GPT-5.2. Попробуйте позже."
