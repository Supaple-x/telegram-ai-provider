import asyncio
import logging

from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command, CommandObject

from src.database.context import ensure_user, get_context, add_message
from src.database.memory import get_memory_texts
from src.database.preferences import get_preferred_model
from src.services.claude import build_system_prompt
from src.services.web_search import search_web, format_search_results
from src.handlers.messages import handle_ai_response, _user_locks

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, bot: Bot) -> None:
    """Handle /search command — web search with AI-powered answer."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

    if not command.args:
        await message.answer(
            "🔍 Поиск в интернете\n\n"
            "Использование:\n"
            "/search <запрос>\n\n"
            "Примеры:\n"
            "• /search Python 3.13 новые фичи\n"
            "• /search курс доллара сегодня\n"
            "• /search best practices FastAPI 2025",
            parse_mode=None,
        )
        return

    query = command.args

    async with _user_locks[user_id]:
        try:
            # Show searching status
            status_msg = await message.answer("🔍 Ищу в интернете...", parse_mode=None)

            # Perform web search
            results = await search_web(query)

            # Delete status message
            try:
                await status_msg.delete()
            except Exception:
                pass

            if not results:
                await message.answer(
                    "🔍 По вашему запросу ничего не найдено. Попробуйте другую формулировку.",
                    parse_mode=None,
                )
                return

            # Format results for Claude prompt
            formatted_results = format_search_results(results)
            search_prompt = (
                f"Пользователь ищет: \"{query}\"\n\n"
                f"Результаты поиска:\n{formatted_results}\n\n"
                f"На основе этих результатов поиска дай подробный ответ на запрос пользователя. "
                f"Используй информацию из результатов и обязательно укажи источники (ссылки)."
            )

            # Get context, memories, and preference in parallel
            context, memories, preferred = await asyncio.gather(
                get_context(user_id),
                get_memory_texts(user_id),
                get_preferred_model(user_id),
            )
            await add_message(user_id, "user", f"/search {query}")
            context.append({"role": "user", "content": search_prompt})

            # Stream AI response
            system_prompt = build_system_prompt(memories)
            await handle_ai_response(
                message, bot, user_id, context, system_prompt, preferred,
            )

        except Exception as e:
            logger.error(f"Error in /search: {e}", exc_info=True)
            await message.answer(
                "❌ Ошибка при поиске. Попробуйте ещё раз.",
                parse_mode=None,
            )
