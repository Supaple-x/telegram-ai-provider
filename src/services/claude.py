import logging
from collections.abc import AsyncGenerator

import anthropic
from config.settings import settings
from config.prompts import CLAUDE_SYSTEM_PROMPT as SYSTEM_PROMPT

logger = logging.getLogger(__name__)

client: anthropic.AsyncAnthropic | None = None


def build_system_prompt(memories: list[str] | None = None) -> str:
    """Build system prompt, optionally including user memories."""
    if not memories:
        return SYSTEM_PROMPT
    memory_block = "\n".join(f"- {m}" for m in memories)
    return f"{SYSTEM_PROMPT}\n\n<user_memory>\n{memory_block}\n</user_memory>"


def init_client() -> None:
    """Initialize Anthropic client."""
    global client
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    logger.info("Anthropic client initialized")


def get_client() -> anthropic.AsyncAnthropic:
    """Get Anthropic client."""
    if client is None:
        raise RuntimeError("Anthropic client not initialized. Call init_client() first.")
    return client


class FallbackError(Exception):
    """Raised when Claude API fails and fallback should be offered."""


def _build_api_messages(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
) -> list[dict]:
    """Build API messages list from conversation history.

    Supports images in any message position (from stored context) and an
    explicit image_data parameter for the current (last) message.
    """
    api_messages = []

    for i, msg in enumerate(messages):
        is_last = i == len(messages) - 1
        # Current-message image param takes priority for the last message
        msg_image = image_data if (is_last and image_data) else msg.get("image_data")

        if msg_image:
            base64_data, media_type = msg_image
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_data,
                    },
                },
                {"type": "text", "text": msg["content"] or "Что на этом изображении?"},
            ]
            api_messages.append({"role": msg["role"], "content": content})
        else:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    return api_messages


async def generate_response(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
    system_prompt: str | None = None,
) -> str:
    """Generate response from Claude (non-streaming)."""
    api_client = get_client()
    api_messages = _build_api_messages(messages, image_data)

    try:
        response = await api_client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system_prompt or SYSTEM_PROMPT,
            messages=api_messages,
        )
        return response.content[0].text

    except anthropic.RateLimitError:
        logger.warning("Rate limit exceeded")
        return "FALLBACK:⚠️ Превышен лимит запросов Claude."

    except anthropic.APIStatusError as e:
        if e.status_code == 529:
            logger.warning("Anthropic API overloaded (529)")
            return "FALLBACK:⚠️ Серверы Claude временно перегружены."
        logger.error(f"Anthropic API status error: {e}")
        return "FALLBACK:❌ Ошибка Claude API."

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return "FALLBACK:❌ Ошибка Claude API."


async def generate_response_stream(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,
    system_prompt: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream response from Claude, yielding text chunks.

    Raises FallbackError if API is unavailable.
    """
    api_client = get_client()
    api_messages = _build_api_messages(messages, image_data)

    try:
        async with api_client.messages.stream(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=system_prompt or SYSTEM_PROMPT,
            messages=api_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    except anthropic.RateLimitError:
        logger.warning("Rate limit exceeded")
        raise FallbackError("⚠️ Превышен лимит запросов Claude.")

    except anthropic.APIStatusError as e:
        if e.status_code == 529:
            logger.warning("Anthropic API overloaded (529)")
            raise FallbackError("⚠️ Серверы Claude временно перегружены.")
        logger.error(f"Anthropic API status error: {e}")
        raise FallbackError("❌ Ошибка Claude API.")

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        raise FallbackError("❌ Ошибка Claude API.")
