import asyncio
import logging
from typing import Any

import httpx
from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config.settings import settings
from src.database.video import add_video_generation
from src.services.claude import generate_response_stream
from src.services.video_gen import generate_video, generate_video_from_image, get_video_client, upload_image_to_fal

logger = logging.getLogger(__name__)
router = Router()

# Per-user locks to prevent multiple simultaneous video generation requests
_user_locks: dict[int, asyncio.Lock] = {}

# Wizard data keys
MODE_TEXT_TO_VIDEO = "text-to-video"
MODE_IMAGE_TO_VIDEO = "image-to-video"


def _get_mode_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for mode selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст → Видео", callback_data="video_mode_text"),
                InlineKeyboardButton(text="🖼️ Фото → Видео", callback_data="video_mode_image"),
            ]
        ]
    )


def _get_aspect_ratio_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for aspect ratio selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="16:9 (горизонтальное)", callback_data="video_ar_16:9"),
                InlineKeyboardButton(text="9:16 (вертикальное)", callback_data="video_ar_9:16"),
            ],
            [
                InlineKeyboardButton(text="1:1 (квадрат)", callback_data="video_ar_1:1"),
            ]
        ]
    )


def _get_duration_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for duration selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 секунд", callback_data="video_dur_5"),
                InlineKeyboardButton(text="8 секунд", callback_data="video_dur_8"),
                InlineKeyboardButton(text="10 секунд", callback_data="video_dur_10"),
            ]
        ]
    )


def _get_resolution_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for resolution selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="720p (быстрее)", callback_data="video_res_720p"),
                InlineKeyboardButton(text="1080p (качественнее)", callback_data="video_res_1080p"),
            ]
        ]
    )


def _get_audio_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for audio selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, с аудио", callback_data="video_audio_yes"),
                InlineKeyboardButton(text="❌ Нет, без аудио", callback_data="video_audio_no"),
            ]
        ]
    )


def _get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for confirmation with AI enhancement option."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✨ Улучшить промпт с AI", callback_data="video_enhance"),
            ],
            [
                InlineKeyboardButton(text="▶️ Запустить генерацию", callback_data="video_generate"),
                InlineKeyboardButton(text="✏️ Изменить промпт", callback_data="video_edit_prompt"),
            ],
            [
                InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data="video_back_audio"),
            ]
        ]
    )


def _get_enhanced_prompt_keyboard(original: str, enhanced: str) -> InlineKeyboardMarkup:
    """Get keyboard for choosing between original and enhanced prompt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Оригинал", callback_data=f"video_use_prompt|{original}"),
            ],
            [
                InlineKeyboardButton(text="✨ Улучшенный AI", callback_data=f"video_use_prompt|{enhanced}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="video_back_confirm"),
            ]
        ]
    )


@router.message(Command("video"))
async def cmd_video(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    """Handle /video command - start wizard or quick generate."""
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

    if not get_video_client():
        logger.warning("Video client not initialized")
        await message.answer(
            "❌ Генерация видео не настроена.\n"
            "Администратору необходимо добавить FAL_KEY.",
            parse_mode=None,
        )
        return

    # If command has args - quick generate
    if command.args:
        await _quick_generate(message, command.args, state)
        return

    # If photo with /video caption - image-to-video quick mode
    if message.photo:
        await _quick_image_to_video(message, state)
        return

    # Otherwise start wizard
    await state.clear()
    await state.update_data({
        "mode": MODE_TEXT_TO_VIDEO,
        "aspect_ratio": "16:9",
        "duration": "5",
        "resolution": "720p",
        "generate_audio": True,
    })

    await message.answer(
        "🎬 Мастер генерации видео\n\n"
        "Выберите режим генерации:",
        parse_mode=None,
        reply_markup=_get_mode_keyboard(),
    )


async def _quick_image_to_video(message: Message, state: FSMContext) -> None:
    """Quick image-to-video with default settings."""
    user_id = message.from_user.id
    
    async with _user_locks[user_id]:
        # Get the largest photo
        photo = message.photo[-1]
        caption = message.caption or "Animate this image"
        
        # Download photo
        file = await message.bot.get_file(photo.file_id)
        image_bytes = await message.bot.download_file(file.file_path)
        image_data = image_bytes.read()
        
        logger.info(f"Quick image-to-video for user {user_id}")
        
        status_msg = await message.answer(
            "🎬 Генерирую видео из фото (это может занять 30-60 секунд)...",
            parse_mode=None,
        )
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        
        # Upload image to fal.storage
        image_url = await upload_image_to_fal(image_data, "input.jpg")
        
        if isinstance(image_url, str):
            await status_msg.delete()
            await message.answer(f"❌ {image_url}", parse_mode=None)
            return
        
        # Generate video
        result = await generate_video_from_image(
            prompt=caption,
            image_url=image_url,
            duration="5",
            resolution="720p",
            aspect_ratio="16:9",
            generate_audio=True,
        )
        
        await status_msg.delete()
        
        if isinstance(result, str):
            await message.answer(f"❌ {result}", parse_mode=None)
            return
        
        await _send_video(message, result, caption, state)


async def _quick_generate(message: Message, prompt: str, state: FSMContext) -> None:
    """Quick generate video with default settings."""
    user_id = message.from_user.id
    
    async with _user_locks[user_id]:
        logger.info(f"Quick generating video for prompt: {prompt[:50]}...")
        
        status_msg = await message.answer(
            "🎬 Генерирую видео (это может занять 30-60 секунд)...",
            parse_mode=None,
        )
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        
        result = await generate_video(
            prompt=prompt,
            duration="5",
            resolution="720p",
            aspect_ratio="16:9",
            generate_audio=True,
        )
        
        await status_msg.delete()
        
        if isinstance(result, str):
            await message.answer(f"❌ {result}", parse_mode=None)
            return
        
        await _send_video(message, result, prompt, state)


async def _send_video(message: Message, result: dict, prompt: str, state: FSMContext) -> None:
    """Download and send video to user."""
    video_url = result["url"]
    seed = result.get("seed", 0)
    
    logger.info(f"Video generated: {video_url}, seed={seed}")
    
    # Save to database
    data = await state.get_data()
    await add_video_generation(
        telegram_id=message.from_user.id,
        prompt=prompt,
        mode=data.get("mode", MODE_TEXT_TO_VIDEO),
        duration=data.get("duration", "5"),
        resolution=data.get("resolution", "720p"),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
        video_url=video_url,
        seed=seed,
    )
    
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
    
    await state.clear()


# --- Wizard callbacks ---

@router.callback_query(F.data == "video_mode_text")
async def callback_mode_text(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle text-to-video mode selection."""
    await state.update_data(mode=MODE_TEXT_TO_VIDEO)
    await state.set_state(VideoWizard.aspect_ratio)
    await callback.message.edit_text(
        "📐 Выберите соотношение сторон:",
        parse_mode=None,
        reply_markup=_get_aspect_ratio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_mode_image")
async def callback_mode_image(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle image-to-video mode selection."""
    await state.update_data(mode=MODE_IMAGE_TO_VIDEO)
    await state.set_state(VideoWizard.aspect_ratio)
    await callback.message.edit_text(
        "📐 Выберите соотношение сторон:",
        parse_mode=None,
        reply_markup=_get_aspect_ratio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video_ar_"))
async def callback_aspect_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle aspect ratio selection."""
    aspect_ratio = callback.data.removeprefix("video_ar_")
    await state.update_data(aspect_ratio=aspect_ratio)
    await state.set_state(VideoWizard.duration)
    await callback.message.edit_text(
        "⏱ Выберите длительность видео:",
        parse_mode=None,
        reply_markup=_get_duration_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video_dur_"))
async def callback_duration(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle duration selection."""
    duration = callback.data.removeprefix("video_dur_")
    await state.update_data(duration=duration)
    await state.set_state(VideoWizard.resolution)
    await callback.message.edit_text(
        "📺 Выберите разрешение видео:",
        parse_mode=None,
        reply_markup=_get_resolution_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video_res_"))
async def callback_resolution(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle resolution selection."""
    resolution = callback.data.removeprefix("video_res_")
    await state.update_data(resolution=resolution)
    await state.set_state(VideoWizard.audio)
    await callback.message.edit_text(
        "🔊 Сгенерировать аудио с lip-sync?",
        parse_mode=None,
        reply_markup=_get_audio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video_audio_"))
async def callback_audio(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle audio selection."""
    audio = callback.data.removeprefix("video_audio_") == "yes"
    await state.update_data(generate_audio=audio)
    await state.set_state(VideoWizard.prompt)
    
    data = await state.get_data()
    mode = data.get("mode", MODE_TEXT_TO_VIDEO)
    
    if mode == MODE_IMAGE_TO_VIDEO:
        await callback.message.edit_text(
            "🖼️ Отправьте фото, которое нужно анимировать.\n\n"
            "Или напишите /cancel для отмены.",
            parse_mode=None,
        )
    else:
        await callback.message.edit_text(
            "📝 Введите описание видео:\n\n"
            "Примеры:\n"
            "• A golden retriever playing fetch in a park at sunset\n"
            "• Cinematic drone shot of Swiss mountains\n"
            "• A chef preparing sushi in a modern kitchen\n\n"
            "💡 Лучше использовать промпты на английском языке.\n"
            "Или напишите /cancel для отмены.",
            parse_mode=None,
        )
    
    await callback.answer()


@router.message(VideoWizard.prompt, F.photo)
async def handle_image_for_i2v(message: Message, state: FSMContext) -> None:
    """Handle image upload for image-to-video mode."""
    data = await state.get_data()
    if data.get("mode") != MODE_IMAGE_TO_VIDEO:
        return
    
    # Get the largest photo
    photo = message.photo[-1]
    
    # Download photo
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)
    image_data = image_bytes.read()
    
    await state.update_data(image_data=image_data)
    await state.set_state(VideoWizard.prompt)
    
    await message.answer(
        "📝 Теперь введите описание движения/действия:\n\n"
        "Примеры:\n"
        "• The character starts walking forward slowly\n"
        "• Camera zooms in on the face\n"
        "• The car drives away into the sunset\n\n"
        "Или напишите /cancel для отмены.",
        parse_mode=None,
    )


@router.message(VideoWizard.prompt, F.text)
async def handle_prompt(message: Message, state: FSMContext) -> None:
    """Handle prompt input."""
    prompt = message.text.strip()
    
    if prompt.lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Генерация видео отменена.", parse_mode=None)
        return
    
    await state.update_data(prompt=prompt)
    await state.set_state(VideoWizard.confirm)
    
    data = await state.get_data()
    mode = data.get("mode", MODE_TEXT_TO_VIDEO)
    
    summary = (
        f"🎬 Настройки генерации:\n\n"
        f"Режим: {'Фото → Видео' if mode == MODE_IMAGE_TO_VIDEO else 'Текст → Видео'}\n"
        f"Формат: {data.get('aspect_ratio', '16:9')}\n"
        f"Длительность: {data.get('duration', '5')} сек\n"
        f"Качество: {data.get('resolution', '720p')}\n"
        f"Аудио: {'✅' if data.get('generate_audio') else '❌'}\n\n"
        f"📝 Промпт:\n{prompt[:200]}"
    )
    
    await message.answer(
        summary,
        parse_mode=None,
        reply_markup=_get_confirm_keyboard(),
    )


@router.callback_query(F.data == "video_edit_prompt")
async def callback_edit_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle edit prompt request."""
    await state.set_state(VideoWizard.prompt)
    await callback.message.edit_text(
        "✏️ Введите новое описание видео:",
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(F.data == "video_back_audio")
async def callback_back_audio(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle back to audio selection."""
    await state.set_state(VideoWizard.audio)
    await callback.message.edit_text(
        "🔊 Сгенерировать аудио с lip-sync?",
        parse_mode=None,
        reply_markup=_get_audio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_back_confirm")
async def callback_back_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle back to confirm screen."""
    await state.set_state(VideoWizard.confirm)
    data = await state.get_data()
    prompt = data.get("prompt", "")
    
    summary = (
        f"🎬 Настройки генерации:\n\n"
        f"📝 Промпт:\n{prompt[:200]}"
    )
    
    await callback.message.edit_text(
        summary,
        parse_mode=None,
        reply_markup=_get_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_enhance")
async def callback_enhance_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Enhance prompt using Claude AI."""
    data = await state.get_data()
    original_prompt = data.get("prompt", "")
    
    await callback.answer("✨ Улучшаю промпт с AI...")
    
    # Build system prompt for video prompt enhancement
    system_prompt = (
        "You are a video prompt engineer. Enhance the user's video generation prompt "
        "to make it more detailed, cinematic, and suitable for AI video generation. "
        "Focus on visual details, camera movement, lighting, and mood. "
        "Keep it concise (1-2 sentences). Return ONLY the enhanced prompt, no explanations."
    )
    
    # Build messages for Claude
    messages = [
        {"role": "user", "content": f"Enhance this video prompt: {original_prompt}"}
    ]
    
    try:
        # Generate enhanced prompt
        enhanced_parts = []
        async for chunk in generate_response_stream(messages, system_prompt=system_prompt):
            enhanced_parts.append(chunk)
        
        enhanced_prompt = "".join(enhanced_parts).strip()
        
        if not enhanced_prompt:
            enhanced_prompt = original_prompt
        
    except Exception as e:
        logger.error(f"Prompt enhancement error: {e}", exc_info=True)
        enhanced_prompt = original_prompt
    
    # Show both options
    await callback.message.edit_text(
        f"✨ Улучшение промпта:\n\n"
        f"📝 Оригинал:\n{original_prompt}\n\n"
        f"✨ Улучшенный AI:\n{enhanced_prompt}",
        parse_mode=None,
        reply_markup=_get_enhanced_prompt_keyboard(original_prompt, enhanced_prompt),
    )


@router.callback_query(F.data.startswith("video_use_prompt|"))
async def callback_use_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle prompt selection (original or enhanced)."""
    new_prompt = callback.data.split("|", 1)[1]
    await state.update_data(prompt=new_prompt)
    await state.set_state(VideoWizard.confirm)
    
    await callback.message.edit_text(
        f"✅ Промпт обновлён:\n\n{new_prompt[:200]}",
        parse_mode=None,
        reply_markup=_get_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_generate")
async def callback_generate(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Start video generation."""
    user_id = callback.from_user.id
    
    async with _user_locks[user_id]:
        data = await state.get_data()
        prompt = data.get("prompt", "")
        mode = data.get("mode", MODE_TEXT_TO_VIDEO)
        duration = data.get("duration", "5")
        resolution = data.get("resolution", "720p")
        aspect_ratio = data.get("aspect_ratio", "16:9")
        generate_audio = data.get("generate_audio", True)
        
        await callback.message.edit_text(
            "🎬 Генерирую видео (это может занять 30-60 секунд)...",
            parse_mode=None,
        )
        await bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_VIDEO)
        
        try:
            if mode == MODE_IMAGE_TO_VIDEO:
                # Upload image to fal.storage
                image_bytes = data.get("image_data")
                if not image_bytes:
                    await callback.message.edit_text(
                        "❌ Ошибка: изображение не найдено",
                        parse_mode=None,
                    )
                    return
                
                image_url = await upload_image_to_fal(image_bytes, "input.jpg")
                
                if isinstance(image_url, str):
                    # Error message
                    await callback.message.edit_text(f"❌ {image_url}", parse_mode=None)
                    return
                
                # Generate video from image
                result = await generate_video_from_image(
                    prompt=prompt,
                    image_url=image_url,
                    duration=duration,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio,
                )
            else:
                # Generate video from text
                result = await generate_video(
                    prompt=prompt,
                    duration=duration,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio,
                )
            
            if isinstance(result, str):
                # Error message
                await callback.message.edit_text(f"❌ {result}", parse_mode=None)
                return
            
            # Send video
            await _send_video(callback.message, result, prompt, state)
            
        except Exception as e:
            logger.error(f"Video generation error: {e}", exc_info=True)
            await callback.message.edit_text(
                f"❌ Ошибка генерации: {str(e)}",
                parse_mode=None,
            )
