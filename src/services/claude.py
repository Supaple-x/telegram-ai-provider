import logging
import anthropic
from config.settings import settings

logger = logging.getLogger(__name__)

client: anthropic.AsyncAnthropic | None = None

SYSTEM_PROMPT = """Ты — Claude Sonnet 4.5, профессиональный AI-консультант от Anthropic.
Версия: Claude Sonnet 4.5 (claude-sonnet-4-5-20250929). Дата знаний: октябрь 2025.

## Твоя роль
Ты — эксперт-консультант широкого профиля. Помогаешь с:
- **Программирование**: код, архитектура, отладка, code review
- **Бизнес**: стратегия, маркетинг, финансы, управление проектами
- **Наука и образование**: объяснение концепций, помощь в исследованиях
- **Право и документы**: анализ договоров, составление текстов (не юридическая консультация)
- **Творчество**: тексты, идеи, копирайтинг, редактура
- **Аналитика**: данные, отчёты, презентации

## Принципы работы
1. **Экспертность** — давай глубокие, профессиональные ответы
2. **Структура** — используй заголовки, списки, примеры кода
3. **Практичность** — предлагай конкретные решения, а не общие фразы
4. **Честность** — если не уверен или вопрос за пределами компетенции, скажи об этом
5. **Адаптивность** — подстраивай уровень сложности под собеседника

## Форматирование
- Используй Markdown: **жирный**, *курсив*, `код`, ```блоки кода```
- Структурируй длинные ответы с заголовками
- Для кода указывай язык: ```python, ```javascript и т.д.

## Работа с файлами
- Изображения: анализируй, описывай, извлекай текст/данные
- Документы (PDF, DOCX, TXT): читай, анализируй, суммаризируй"""


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


async def generate_response(
    messages: list[dict],
    image_data: tuple[str, str] | None = None,  # (base64_data, media_type)
) -> str:
    """
    Generate response from Claude.

    Args:
        messages: Conversation history
        image_data: Optional tuple of (base64_data, media_type) for image analysis

    Returns:
        Generated response text
    """
    api_client = get_client()

    # Build the last user message with optional image
    api_messages = []

    for msg in messages[:-1]:  # All messages except the last one
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    # Handle the last message (potentially with image)
    last_msg = messages[-1]
    if image_data:
        base64_data, media_type = image_data
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64_data,
                },
            },
            {"type": "text", "text": last_msg["content"] or "Что на этом изображении?"},
        ]
        api_messages.append({"role": "user", "content": content})
    else:
        api_messages.append({"role": last_msg["role"], "content": last_msg["content"]})

    try:
        response = await api_client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=SYSTEM_PROMPT,
            messages=api_messages,
        )

        return response.content[0].text

    except anthropic.RateLimitError:
        logger.warning("Rate limit exceeded")
        return "⚠️ Превышен лимит запросов. Пожалуйста, подождите немного и попробуйте снова."

    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        return "❌ Произошла ошибка при обращении к AI. Попробуйте позже."
