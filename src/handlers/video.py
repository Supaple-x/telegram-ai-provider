import asyncio
import logging

import httpx
from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from src.services.video_gen import generate_video, get_video_client

logger = logging.getLogger(__name__)
router = Router()

# Per-user locks to prevent multiple simultaneous video generation requests
_user_locks: dict[int, asyncio.Lock] = {}


@router.message(Command("video"))
async def cmd_video(message: Message, command: CommandObject, bot: Bot) -> None:
    """Generate video from text prompt using Seedance 1.5 Pro."""
    user_id = message.from_user.id
    
    # Initialize per-user lock if not exists
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    
    # Check if user already has a pending video generation
    if _user_locks[user_id].locked():
        await message.answer(
            "⏳ У вас уже есть активная генерация видео. Пожалуйста, дождитесь завершения.",
            parse_mode=None,
        )
        return
    
    async with _user_locks[user_id]:
        logger.info(f"Received /video command from user {user_id}")
        
        if not get_video_client():
            logger.warning("Video client not initialized")
            await message.answer(
                "❌ Генерация видео не настроена.\n"
                "Администратору необходимо добавить FAL_KEY.",
                parse_mode=None,
            )
            return
        
        if not command.args:
            await message.answer(
                "🎬 Генерация видео с Seedance 1.5 Pro\n\n"
                "Использование:\n"
                "/video <описание видео>\n\n"
                "Примеры:\n"
                "• /video A golden retriever playing fetch in a park at sunset\n"
                "• /video Cinematic drone shot of Swiss mountains\n"
                "• /video A chef preparing sushi in a modern kitchen\n\n"
                "Параметры по умолчанию:\n"
                "• Длительность: 5 секунд\n"
                "• Качество: 720p\n"
                "• Формат: 16:9\n"
                "• Аудио: включено\n\n"
                "💡 Лучше использовать промпты на английском языке.",
                parse_mode=None,
            )
            return
        
        prompt = command.args
        logger.info(f"Generating video for prompt: {prompt[:50]}...")
        
        # Show generating status
        status_msg = await message.answer(
            "🎬 Генерирую видео (это может занять 30-60 секунд)...",
            parse_mode=None,
        )
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        
        # Generate video with default settings
        result = await generate_video(
            prompt=prompt,
            duration="5",
            resolution="720p",
            aspect_ratio="16:9",
            generate_audio=True,
        )
        
        # Delete status message
        await status_msg.delete()
        
        if isinstance(result, str):
            # Error message
            await message.answer(f"❌ {result}", parse_mode=None)
            return
        
        # result is dict: {"url": str, "seed": int}
        video_url = result["url"]
        seed = result.get("seed", 0)
        
        logger.info(f"Video generated: {video_url}, seed={seed}")
        
        # Download video file
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(video_url)
                
                if response.status_code != 200:
                    await message.answer(
                        f"❌ Не удалось скачать видео (код {response.status_code})",
                        parse_mode=None,
                    )
                    return
                
                video_bytes = response.content
                
        except httpx.TimeoutException:
            await message.answer(
                "❌ Превышено время скачивания видео",
                parse_mode=None,
            )
            return
        except Exception as e:
            logger.error(f"Video download error: {e}", exc_info=True)
            await message.answer(
                f"❌ Ошибка скачивания видео: {str(e)}",
                parse_mode=None,
            )
            return
        
        # Check file size (Telegram limit: 50MB for regular bots)
        if len(video_bytes) > 50 * 1024 * 1024:
            # Send as link if too large
            await message.answer(
                f"🎬 {prompt[:200]}\n\n"
                f"Seedance 1.5 Pro (seed={seed})\n\n"
                f"⚠️ Видео слишком большое для отправки файлом, скачайте по ссылке:\n"
                f"{video_url}",
                parse_mode=None,
            )
            return
        
        # Send video
        filename = "generated.mp4"
        video = BufferedInputFile(video_bytes, filename=filename)
        
        await message.answer_video(
            video,
            caption=f"🎬 {prompt[:200]}\n\nSeedance 1.5 Pro (seed={seed})",
            parse_mode=None,
        )
