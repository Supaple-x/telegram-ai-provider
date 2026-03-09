import asyncio
import base64
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
from src.database.context import ensure_user
from src.database.video import add_video_generation
from src.services.claude import generate_response_stream
from src.services import evolink as evolink_svc
from src.services import video_gen as fal_svc
from src.services import wavespeed as wavespeed_svc
from src.services.evolink import generate_i2v_kling, generate_v2v_kling
from src.services.video_gen import (
    generate_video, generate_video_from_image,
    upload_image_to_fal, upload_video_to_fal,
)
from src.services.wavespeed import (
    generate_v2v_wan, upload_video_to_wavespeed,
)
from src.states.video import VideoWizard

logger = logging.getLogger(__name__)
router = Router()

# Per-user locks to prevent multiple simultaneous video generation requests
_user_locks: dict[int, asyncio.Lock] = {}

# Wizard data keys
MODE_TEXT_TO_VIDEO = "text-to-video"
MODE_IMAGE_TO_VIDEO = "image-to-video"
MODE_VIDEO_TO_VIDEO = "video-to-video"

# I2V model identifiers
I2V_MODEL_SEEDANCE = "seedance"
I2V_MODEL_KLING = "kling_o3"

# V2V model identifiers
V2V_MODEL_WAN = "wan2.2"
V2V_MODEL_KLING = "kling_o3"

# Strength presets for Wan 2.2
WAN_STRENGTH_PRESETS = {
    "low": 0.3,
    "medium": 0.6,
    "high": 0.85,
}

# Model display names (for captions and UI)
MODEL_DISPLAY_NAMES = {
    "seedance": "Seedance 1.5 Pro",
    "wan2.2": "Wan 2.2",
    "kling_o3": "Kling O3",
}

# Max video upload size (Telegram Bot API limit: 20MB)
MAX_VIDEO_UPLOAD_SIZE = 20 * 1024 * 1024

# Progress bar settings
_TICK_INTERVAL = 4.0  # seconds between ticks (chat action refresh)
_TICKS_PER_FRAME = 2  # advance progress every N ticks (~8s per frame)
_PROGRESS_FRAMES = [
    "🎬 Записываю видео\n\n[░░░░░░░░░░░░░░░░░░░░] 0%",
    "🎬 Записываю видео\n\n[█░░░░░░░░░░░░░░░░░░░] 5%",
    "🎬 Записываю видео\n\n[██░░░░░░░░░░░░░░░░░░] 10%",
    "🎬 Записываю видео\n\n[███░░░░░░░░░░░░░░░░░] 15%",
    "🎬 Записываю видео\n\n[████░░░░░░░░░░░░░░░░] 20%",
    "🎬 Записываю видео\n\n[█████░░░░░░░░░░░░░░░] 25%",
    "🎬 Записываю видео\n\n[██████░░░░░░░░░░░░░░] 30%",
    "🎬 Записываю видео\n\n[███████░░░░░░░░░░░░░] 35%",
    "🎬 Записываю видео\n\n[████████░░░░░░░░░░░░] 40%",
    "🎬 Записываю видео\n\n[█████████░░░░░░░░░░░] 45%",
    "🎬 Записываю видео\n\n[██████████░░░░░░░░░░] 50%",
    "🎬 Записываю видео\n\n[███████████░░░░░░░░░] 55%",
    "🎬 Записываю видео\n\n[████████████░░░░░░░░] 60%",
    "🎬 Записываю видео\n\n[█████████████░░░░░░░] 65%",
    "🎬 Записываю видео\n\n[██████████████░░░░░░] 70%",
    "🎬 Записываю видео\n\n[███████████████░░░░░] 75%",
    "🎬 Записываю видео\n\n[████████████████░░░░] 80%",
    "🎬 Записываю видео\n\n[█████████████████░░░] 85%",
    "🎬 Записываю видео\n\n[██████████████████░░] 90%",
    "🎬 Записываю видео\n\n[███████████████████░] 95%",
]


async def _run_progress(
    bot: Bot,
    chat_id: int,
    status_msg: Message,
    stop_event: asyncio.Event,
) -> None:
    """Update status message with progress bar and send chat actions."""
    frame = 1  # Frame 0 already shown at creation
    tick = 0
    while not stop_event.is_set():
        await asyncio.sleep(_TICK_INTERVAL)
        if stop_event.is_set():
            break
        # Send "recording video" chat action every tick
        try:
            await bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)
        except Exception:
            pass
        # Update progress bar text every N ticks
        tick += 1
        if tick >= _TICKS_PER_FRAME and frame < len(_PROGRESS_FRAMES):
            tick = 0
            try:
                await status_msg.edit_text(
                    _PROGRESS_FRAMES[frame], parse_mode=None
                )
            except Exception:
                pass
            frame += 1


def _get_mode_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for mode selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст → Видео", callback_data="video_mode_text"),
                InlineKeyboardButton(text="🖼️ Фото → Видео", callback_data="video_mode_image"),
            ],
            [
                InlineKeyboardButton(text="🎞️ Видео → Видео", callback_data="video_mode_v2v"),
            ],
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


def _get_duration_keyboard(kling_mode: bool = False) -> InlineKeyboardMarkup:
    """Get keyboard for duration selection."""
    if kling_mode:
        # Kling O3 supports 5 and 10 second durations
        buttons = [
            InlineKeyboardButton(text="5 секунд", callback_data="video_dur_5"),
            InlineKeyboardButton(text="10 секунд", callback_data="video_dur_10"),
        ]
    else:
        buttons = [
            InlineKeyboardButton(text="5 секунд", callback_data="video_dur_5"),
            InlineKeyboardButton(text="8 секунд", callback_data="video_dur_8"),
            InlineKeyboardButton(text="10 секунд", callback_data="video_dur_10"),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


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


def _get_enhanced_prompt_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for choosing between original and enhanced prompt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Оригинал", callback_data="video_use_original"),
            ],
            [
                InlineKeyboardButton(text="✨ Улучшенный AI", callback_data="video_use_enhanced"),
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="video_back_confirm"),
            ]
        ]
    )


# --- Video-to-video keyboards ---


def _availability_icon(has_key: bool, balance_ok: bool) -> str:
    """Get availability icon: ✅ / 💸 / 🔒."""
    if not has_key:
        return "🔒"
    if not balance_ok:
        return "💸"
    return "✅"


def _get_i2v_model_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for i2v model selection with availability indicators."""
    fal_icon = _availability_icon(fal_svc.get_video_client(), fal_svc._balance_ok)
    evo_icon = _availability_icon(evolink_svc.get_evolink_client(), evolink_svc._balance_ok)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{fal_icon} Seedance 1.5 Pro (~$0.05/с)",
                    callback_data="i2v_model_seedance",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{evo_icon} Kling O3 (~$0.08/с)",
                    callback_data="i2v_model_kling",
                ),
            ],
        ]
    )


def _get_v2v_model_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for v2v model selection with availability indicators."""
    wan_icon = _availability_icon(wavespeed_svc.get_wavespeed_client(), wavespeed_svc._balance_ok)
    evo_icon = _availability_icon(evolink_svc.get_evolink_client(), evolink_svc._balance_ok)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{wan_icon} Wan 2.2 (~$0.01-0.02/с)",
                    callback_data="v2v_model_wan",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{evo_icon} Kling O3 (~$0.08/с, качественнее)",
                    callback_data="v2v_model_kling",
                ),
            ],
        ]
    )


def _get_strength_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for Wan 2.2 transformation strength."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Слабое (30%)", callback_data="v2v_str_low"),
                InlineKeyboardButton(text="🟡 Среднее (60%)", callback_data="v2v_str_medium"),
            ],
            [
                InlineKeyboardButton(text="🔴 Сильное (85%)", callback_data="v2v_str_high"),
            ],
        ]
    )


def _get_v2v_resolution_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for Wan 2.2 resolution."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="480p (дешевле)", callback_data="v2v_res_480p"),
                InlineKeyboardButton(text="720p (качественнее)", callback_data="v2v_res_720p"),
            ]
        ]
    )


def _get_v2v_quality_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for Kling O3 quality selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="720p (быстрее)", callback_data="v2v_qual_720p"),
                InlineKeyboardButton(text="1080p (качественнее)", callback_data="v2v_qual_1080p"),
            ]
        ]
    )


def _get_v2v_audio_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for Kling O3 audio preservation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить аудио", callback_data="v2v_audio_yes"),
                InlineKeyboardButton(text="❌ Без аудио", callback_data="v2v_audio_no"),
            ]
        ]
    )


# --- AI style suggestions for image-to-video ---

_STYLES = {
    "neutral": "😐 Нейтральный",
    "ironic": "😏 Ироничный",
    "grotesque": "🎭 Гротеск",
    "cartoon": "🎪 Мультяшный",
    "comic": "😂 Комичный",
}


def _get_style_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard for AI style prompt selection."""
    keys = list(_STYLES.items())
    rows = []
    for i in range(0, len(keys), 2):
        row = [
            InlineKeyboardButton(text=label, callback_data=f"video_style_{key}")
            for key, label in keys[i:i + 2]
        ]
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="✏️ Свой промпт", callback_data="video_style_custom")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _generate_style_prompts(image_data: bytes) -> dict[str, str] | None:
    """Analyze image with Claude and generate 5 styled video animation prompts."""
    b64 = base64.b64encode(image_data).decode()

    system_prompt = (
        "You are a video prompt engineer. Look at the image and generate 5 short video animation prompts "
        "in different styles. Each prompt: 1-2 sentences IN RUSSIAN, describing motion/action.\n\n"
        "Return EXACTLY in this format, one per line, no extra text:\n"
        "neutral: <реалистичное естественное движение>\n"
        "ironic: <ироничный неожиданный поворот>\n"
        "grotesque: <сюрреалистичное преувеличенное искажение>\n"
        "cartoon: <мультяшное игривое преувеличение>\n"
        "comic: <смешная комичная ситуация>"
    )

    messages = [{"role": "user", "content": "Generate 5 styled video animation prompts for this image."}]

    try:
        parts: list[str] = []
        async for chunk in generate_response_stream(
            messages, image_data=(b64, "image/jpeg"), system_prompt=system_prompt,
        ):
            parts.append(chunk)

        text = "".join(parts).strip()
        result: dict[str, str] = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            for key in _STYLES:
                if line.lower().startswith(f"{key}:"):
                    prompt_text = line[len(key) + 1:].strip().strip('"').strip("'")
                    if prompt_text:
                        result[key] = prompt_text
                    break

        if len(result) < 3:
            logger.warning(f"Failed to parse style prompts: {text[:200]}")
            return None
        return result

    except Exception as e:
        logger.error(f"Style prompt generation error: {e}", exc_info=True)
        return None


async def _translate_to_english(text: str) -> str:
    """Translate prompt to English for Seedance API (if it contains Cyrillic)."""
    if not any("\u0400" <= ch <= "\u04ff" for ch in text):
        return text  # already English

    messages = [{"role": "user", "content": text}]
    system_prompt = (
        "Translate the following video generation prompt to English. "
        "Return ONLY the translation, no explanations. "
        "Keep it cinematic and descriptive for AI video generation."
    )
    try:
        parts: list[str] = []
        async for chunk in generate_response_stream(messages, system_prompt=system_prompt):
            parts.append(chunk)
        return "".join(parts).strip() or text
    except Exception as e:
        logger.warning(f"Translation failed, using original: {e}")
        return text


async def _show_style_suggestions(
    message: Message, state: FSMContext, image_data: bytes,
) -> None:
    """Analyze image with AI and show styled prompt suggestions."""
    status_msg = await message.answer("🔍 Анализирую изображение...", parse_mode=None)

    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:
        pass

    suggestions = await _generate_style_prompts(image_data)

    if not suggestions:
        await status_msg.edit_text(
            "📝 Не удалось проанализировать. Введите описание движения/действия:\n\n"
            "Или напишите /cancel для отмены.",
            parse_mode=None,
        )
        await state.set_state(VideoWizard.prompt)
        return

    await state.update_data(style_prompts=suggestions)
    await state.set_state(VideoWizard.style_select)

    text = "🎨 AI предлагает варианты промптов:\n\n"
    for key, prompt_text in suggestions.items():
        label = _STYLES.get(key, key)
        clean = prompt_text.replace("`", "'")
        text += f"{label}:\n`{clean}`\n\n"
    text += "Выберите стиль или введите свой промпт:"

    await status_msg.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=_get_style_keyboard(),
    )


@router.message(Command("video"))
async def cmd_video(message: Message, command: CommandObject, state: FSMContext, bot: Bot) -> None:
    """Handle /video command - start wizard or quick generate."""
    user_id = message.from_user.id
    await ensure_user(user_id, message.from_user.username)

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

    if not fal_svc.get_video_client() and not evolink_svc.get_evolink_client():
        logger.warning("No video clients initialized")
        await message.answer(
            "❌ Генерация видео не настроена.\n"
            "Администратору необходимо добавить FAL_KEY или EVOLINK_API_KEY.",
            parse_mode=None,
        )
        return

    # If photo with /video - image-to-video with AI suggestions
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        image_bytes_io = await bot.download_file(file.file_path)
        await state.update_data(
            mode=MODE_IMAGE_TO_VIDEO, image_data=image_bytes_io.read(),
            quick_mode=True, duration="5", resolution="720p",
            aspect_ratio="16:9", generate_audio=True,
        )
        await _show_style_suggestions(message, state, (await state.get_data())["image_data"])
        return

    # If command has args - quick text-to-video
    if command.args:
        await _quick_generate(message, command.args, state)
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


async def _quick_generate(message: Message, prompt: str, state: FSMContext) -> None:
    """Quick generate video with default settings."""
    user_id = message.from_user.id

    async with _user_locks[user_id]:
        logger.info(f"Quick generating video for prompt: {prompt[:50]}...")

        # Translate to English for Seedance API
        api_prompt = await _translate_to_english(prompt)

        status_msg = await message.answer(
            _PROGRESS_FRAMES[0], parse_mode=None,
        )
        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(
            _run_progress(message.bot, message.chat.id, status_msg, stop_event)
        )

        try:
            result = await generate_video(
                prompt=api_prompt,
                duration="5",
                resolution="720p",
                aspect_ratio="16:9",
                generate_audio=True,
            )

            stop_event.set()
            await progress_task

            if isinstance(result, str):
                await status_msg.edit_text(f"❌ {result}", parse_mode=None)
                return

            await _send_video(message, result, prompt, state, status_msg)
        except Exception as e:
            stop_event.set()
            await progress_task
            logger.error(f"Video generation error: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ Ошибка генерации: {e}", parse_mode=None
            )


async def _send_video(
    message: Message,
    result: dict,
    prompt: str,
    state: FSMContext,
    status_msg: Message | None = None,
    user_id: int | None = None,
) -> None:
    """Download and send video to user."""
    video_url = result["url"]
    seed = result.get("seed", 0)
    telegram_id = user_id or message.from_user.id

    logger.info(f"Video generated: {video_url}, seed={seed}")

    # Save to database
    data = await state.get_data()
    v2v_model = data.get("v2v_model", "")
    i2v_model = data.get("i2v_model", "")
    if v2v_model:
        model_name = v2v_model
    elif i2v_model and i2v_model != I2V_MODEL_SEEDANCE:
        model_name = i2v_model
    else:
        model_name = "seedance"
    await add_video_generation(
        telegram_id=telegram_id,
        prompt=prompt,
        mode=data.get("mode", MODE_TEXT_TO_VIDEO),
        duration=data.get("duration", "5"),
        resolution=data.get("resolution", "720p"),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
        video_url=video_url,
        seed=seed,
        model=model_name,
        source_video_url=data.get("source_video_url"),
    )

    # Update status to "sending"
    if status_msg:
        try:
            await status_msg.edit_text(
                "📤 Отправляю видео...", parse_mode=None
            )
        except Exception:
            pass
    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass

    # Download video file
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(video_url)

            if response.status_code != 200:
                error_text = f"❌ Не удалось скачать видео (код {response.status_code})"
                if status_msg:
                    await status_msg.edit_text(error_text, parse_mode=None)
                else:
                    await message.answer(error_text, parse_mode=None)
                return

            video_bytes = response.content

    except httpx.TimeoutException:
        error_text = "❌ Превышено время скачивания видео"
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=None)
        else:
            await message.answer(error_text, parse_mode=None)
        return
    except Exception as e:
        logger.error(f"Video download error: {e}", exc_info=True)
        error_text = f"❌ Ошибка скачивания видео: {e}"
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=None)
        else:
            await message.answer(error_text, parse_mode=None)
        return

    # Check file size (Telegram limit: 50MB for regular bots)
    display_model = MODEL_DISPLAY_NAMES.get(model_name, model_name)
    seed_text = f" (seed={seed})" if seed else ""
    if len(video_bytes) > 50 * 1024 * 1024:
        text = (
            f"🎬 {prompt[:200]}\n\n"
            f"{display_model}{seed_text}\n\n"
            f"⚠️ Видео слишком большое для отправки файлом, скачайте по ссылке:\n"
            f"{video_url}"
        )
        if status_msg:
            await status_msg.edit_text(text, parse_mode=None)
        else:
            await message.answer(text, parse_mode=None)
        return

    # Delete status message before sending video
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass

    # Send video
    filename = "generated.mp4"
    video = BufferedInputFile(video_bytes, filename=filename)

    await message.answer_video(
        video,
        caption=f"🎬 {prompt[:200]}\n\n{display_model}{seed_text}",
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
    """Handle image-to-video mode selection — show model choice."""
    await state.update_data(mode=MODE_IMAGE_TO_VIDEO)
    await state.set_state(VideoWizard.i2v_model)
    await callback.message.edit_text(
        "🖼️ Фото → Видео\n\n"
        "Выберите модель для генерации:",
        parse_mode=None,
        reply_markup=_get_i2v_model_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("i2v_model_"))
async def callback_i2v_model(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle i2v model selection."""
    model_key = callback.data.removeprefix("i2v_model_")
    model = I2V_MODEL_KLING if model_key == "kling" else I2V_MODEL_SEEDANCE

    # Check availability
    if model == I2V_MODEL_SEEDANCE and not fal_svc.is_available():
        if not fal_svc.get_video_client():
            await callback.answer("Seedance не настроен (нет FAL_KEY)", show_alert=True)
        else:
            await callback.answer("Баланс fal.ai исчерпан 💸", show_alert=True)
        return
    if model == I2V_MODEL_KLING and not evolink_svc.is_available():
        if not evolink_svc.get_evolink_client():
            await callback.answer("Kling O3 не настроен (нет EVOLINK_API_KEY)", show_alert=True)
        else:
            await callback.answer("Баланс EvoLink исчерпан 💸", show_alert=True)
        return

    await state.update_data(i2v_model=model)
    await state.set_state(VideoWizard.aspect_ratio)
    await callback.message.edit_text(
        "📐 Выберите соотношение сторон:",
        parse_mode=None,
        reply_markup=_get_aspect_ratio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_mode_v2v")
async def callback_mode_v2v(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle video-to-video mode selection."""
    # Check if at least one v2v provider is available
    wan_ok = wavespeed_svc.get_wavespeed_client()
    kling_ok = evolink_svc.get_evolink_client()
    if not wan_ok and not kling_ok:
        await callback.message.edit_text(
            "❌ Видео → Видео не настроено.\n"
            "Нужен WAVESPEED_API_KEY или EVOLINK_API_KEY.",
            parse_mode=None,
        )
        await callback.answer()
        return

    await state.update_data(mode=MODE_VIDEO_TO_VIDEO)
    await state.set_state(VideoWizard.v2v_model)
    await callback.message.edit_text(
        "🎞️ Видео → Видео\n\n"
        "Выберите модель для трансформации:",
        parse_mode=None,
        reply_markup=_get_v2v_model_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v2v_model_"))
async def callback_v2v_model(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle v2v model selection."""
    model_key = callback.data.removeprefix("v2v_model_")
    model = V2V_MODEL_WAN if model_key == "wan" else V2V_MODEL_KLING

    # Check availability
    if model == V2V_MODEL_WAN and not wavespeed_svc.is_available():
        if not wavespeed_svc.get_wavespeed_client():
            await callback.answer("Wan 2.2 не настроен (нет WAVESPEED_API_KEY)", show_alert=True)
        else:
            await callback.answer("Баланс WaveSpeedAI исчерпан 💸", show_alert=True)
        return
    if model == V2V_MODEL_KLING and not evolink_svc.is_available():
        if not evolink_svc.get_evolink_client():
            await callback.answer("Kling O3 не настроен (нет EVOLINK_API_KEY)", show_alert=True)
        else:
            await callback.answer("Баланс EvoLink исчерпан 💸", show_alert=True)
        return

    await state.update_data(v2v_model=model)
    await state.set_state(VideoWizard.v2v_video_upload)
    await callback.message.edit_text(
        "📹 Отправьте видео, которое нужно трансформировать.\n\n"
        "⚠️ Максимальный размер: 20 МБ.\n"
        "Или напишите /cancel для отмены.",
        parse_mode=None,
    )
    await callback.answer()


@router.message(VideoWizard.v2v_video_upload, F.video)
async def handle_video_upload_for_v2v(message: Message, state: FSMContext, bot: Bot) -> None:
    """Handle video file upload for v2v mode."""
    video = message.video

    if video.file_size and video.file_size > MAX_VIDEO_UPLOAD_SIZE:
        await message.answer(
            "⚠️ Видео слишком большое. Максимум 20 МБ.\n"
            "Попробуйте сжать или обрезать видео.",
            parse_mode=None,
        )
        return

    status_msg = await message.answer("📤 Загружаю видео...", parse_mode=None)

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    except Exception:
        pass

    # Download video from Telegram
    file = await bot.get_file(video.file_id)
    video_bytes_io = await bot.download_file(file.file_path)
    video_bytes = video_bytes_io.read()

    data = await state.get_data()
    v2v_model = data.get("v2v_model", V2V_MODEL_WAN)
    filename = video.file_name or "input.mp4"

    # Upload to appropriate storage
    if v2v_model == V2V_MODEL_WAN:
        source_url = await upload_video_to_wavespeed(video_bytes, filename)
    else:
        # Kling O3 needs a public URL — upload to fal.ai storage
        source_url = await upload_video_to_fal(video_bytes, filename)

    if not source_url.startswith("http"):
        await status_msg.edit_text(f"❌ {source_url}", parse_mode=None)
        return

    # Store URL, drop raw bytes from state to save memory
    await state.update_data(source_video_url=source_url)

    try:
        await status_msg.delete()
    except Exception:
        pass

    # Branch by model for next steps
    if v2v_model == V2V_MODEL_WAN:
        await state.set_state(VideoWizard.v2v_strength)
        await message.answer(
            "💪 Выберите силу трансформации:\n\n"
            "🟢 Слабое — минимальные изменения, сохраняет структуру\n"
            "🟡 Среднее — заметная стилизация\n"
            "🔴 Сильное — максимальная трансформация",
            parse_mode=None,
            reply_markup=_get_strength_keyboard(),
        )
    else:
        # Kling O3: quality → audio → prompt
        await state.set_state(VideoWizard.resolution)
        await message.answer(
            "📺 Выберите качество выходного видео:",
            parse_mode=None,
            reply_markup=_get_v2v_quality_keyboard(),
        )


@router.message(VideoWizard.v2v_video_upload, F.video_note)
async def handle_video_note_for_v2v(message: Message, state: FSMContext, bot: Bot) -> None:
    """Handle video note (round video) upload for v2v mode."""
    video_note = message.video_note

    if video_note.file_size and video_note.file_size > MAX_VIDEO_UPLOAD_SIZE:
        await message.answer("⚠️ Видео слишком большое. Максимум 20 МБ.", parse_mode=None)
        return

    status_msg = await message.answer("📤 Загружаю видео...", parse_mode=None)

    file = await bot.get_file(video_note.file_id)
    video_bytes_io = await bot.download_file(file.file_path)
    video_bytes = video_bytes_io.read()

    data = await state.get_data()
    v2v_model = data.get("v2v_model", V2V_MODEL_WAN)

    if v2v_model == V2V_MODEL_WAN:
        source_url = await upload_video_to_wavespeed(video_bytes, "input.mp4")
    else:
        source_url = await upload_video_to_fal(video_bytes, "input.mp4")

    if not source_url.startswith("http"):
        await status_msg.edit_text(f"❌ {source_url}", parse_mode=None)
        return

    await state.update_data(source_video_url=source_url)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if v2v_model == V2V_MODEL_WAN:
        await state.set_state(VideoWizard.v2v_strength)
        await message.answer(
            "💪 Выберите силу трансформации:",
            parse_mode=None,
            reply_markup=_get_strength_keyboard(),
        )
    else:
        await state.set_state(VideoWizard.resolution)
        await message.answer(
            "📺 Выберите качество выходного видео:",
            parse_mode=None,
            reply_markup=_get_v2v_quality_keyboard(),
        )


@router.callback_query(F.data.startswith("v2v_str_"))
async def callback_v2v_strength(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle Wan 2.2 strength selection."""
    strength_key = callback.data.removeprefix("v2v_str_")
    strength_value = WAN_STRENGTH_PRESETS.get(strength_key, 0.6)
    await state.update_data(v2v_strength=strength_value)

    await state.set_state(VideoWizard.resolution)
    await callback.message.edit_text(
        "📺 Выберите разрешение:",
        parse_mode=None,
        reply_markup=_get_v2v_resolution_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v2v_res_"))
async def callback_v2v_resolution(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle Wan 2.2 resolution selection."""
    resolution = callback.data.removeprefix("v2v_res_")
    await state.update_data(resolution=resolution)
    await state.set_state(VideoWizard.prompt)
    await callback.message.edit_text(
        "📝 Введите описание желаемого результата:\n\n"
        "Примеры:\n"
        "• Трансформировать в стиль аниме\n"
        "• Сделать как масляную живопись\n"
        "• Добавить киберпанк атмосферу\n\n"
        "Или напишите /cancel для отмены.",
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v2v_qual_"))
async def callback_v2v_quality(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle Kling O3 quality selection."""
    quality = callback.data.removeprefix("v2v_qual_")
    await state.update_data(resolution=quality)

    await state.set_state(VideoWizard.audio)
    await callback.message.edit_text(
        "🔊 Сохранить оригинальное аудио из видео?",
        parse_mode=None,
        reply_markup=_get_v2v_audio_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v2v_audio_"))
async def callback_v2v_audio(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle Kling O3 audio preservation selection."""
    keep_audio = callback.data.removeprefix("v2v_audio_") == "yes"
    await state.update_data(generate_audio=keep_audio)
    await state.set_state(VideoWizard.prompt)
    await callback.message.edit_text(
        "📝 Введите описание желаемого результата:\n\n"
        "Примеры:\n"
        "• Трансформировать в стиль аниме\n"
        "• Сделать как масляную живопись\n"
        "• Добавить киберпанк атмосферу\n\n"
        "Или напишите /cancel для отмены.",
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video_ar_"))
async def callback_aspect_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle aspect ratio selection."""
    aspect_ratio = callback.data.removeprefix("video_ar_")
    await state.update_data(aspect_ratio=aspect_ratio)
    await state.set_state(VideoWizard.duration)
    data = await state.get_data()
    kling_mode = data.get("i2v_model") == I2V_MODEL_KLING
    await callback.message.edit_text(
        "⏱ Выберите длительность видео:",
        parse_mode=None,
        reply_markup=_get_duration_keyboard(kling_mode=kling_mode),
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
    """Handle image upload for image-to-video mode — suggest AI prompts."""
    data = await state.get_data()
    if data.get("mode") != MODE_IMAGE_TO_VIDEO:
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes_io = await message.bot.download_file(file.file_path)
    image_data = image_bytes_io.read()

    await state.update_data(image_data=image_data)
    await _show_style_suggestions(message, state, image_data)


@router.callback_query(F.data.startswith("video_style_"))
async def callback_style_select(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Handle style selection for image-to-video prompts."""
    style = callback.data.removeprefix("video_style_")

    if style == "custom":
        await state.set_state(VideoWizard.prompt)
        await callback.message.edit_text(
            "✏️ Введите описание движения/действия:\n\n"
            "Или напишите /cancel для отмены.",
            parse_mode=None,
        )
        await callback.answer()
        return

    data = await state.get_data()
    suggestions = data.get("style_prompts", {})
    prompt = suggestions.get(style, "")

    if not prompt:
        await callback.answer("Ошибка: промпт не найден", show_alert=True)
        return

    await state.update_data(prompt=prompt)
    await callback.answer()

    if data.get("quick_mode"):
        # Quick mode: generate immediately with defaults
        await callback_generate(callback, state, bot)
    else:
        # Wizard mode: show confirm screen
        await state.set_state(VideoWizard.confirm)
        summary = _build_summary(data, prompt)
        await callback.message.edit_text(
            summary,
            parse_mode=None,
            reply_markup=_get_confirm_keyboard(),
        )


@router.message(VideoWizard.style_select, F.text)
async def handle_text_in_style_select(message: Message, state: FSMContext) -> None:
    """Handle custom prompt typed during style selection."""
    await state.set_state(VideoWizard.prompt)
    await handle_prompt(message, state)


@router.message(Command("cancel"))
async def cmd_cancel_video(message: Message, state: FSMContext) -> None:
    """Cancel video generation wizard."""
    current_state = await state.get_state()
    if current_state and current_state.startswith("VideoWizard"):
        await state.clear()
        await message.answer("❌ Генерация видео отменена.", parse_mode=None)


def _build_summary(data: dict, prompt: str) -> str:
    """Build settings summary for confirm screen."""
    mode = data.get("mode", MODE_TEXT_TO_VIDEO)

    if mode == MODE_VIDEO_TO_VIDEO:
        v2v_model = data.get("v2v_model", V2V_MODEL_WAN)
        model_label = MODEL_DISPLAY_NAMES.get(v2v_model, v2v_model)
        summary = (
            f"🎬 Настройки генерации:\n\n"
            f"Режим: Видео → Видео\n"
            f"Модель: {model_label}\n"
            f"Качество: {data.get('resolution', '720p')}\n"
        )
        if v2v_model == V2V_MODEL_WAN:
            strength = data.get("v2v_strength", 0.6)
            summary += f"Сила трансформации: {int(strength * 100)}%\n"
        else:
            audio = "✅ сохранить" if data.get("generate_audio") else "❌ без аудио"
            summary += f"Аудио: {audio}\n"
    else:
        mode_label = "Фото → Видео" if mode == MODE_IMAGE_TO_VIDEO else "Текст → Видео"
        summary = (
            f"🎬 Настройки генерации:\n\n"
            f"Режим: {mode_label}\n"
        )
        # Show model for i2v if not default
        if mode == MODE_IMAGE_TO_VIDEO:
            i2v_model = data.get("i2v_model", I2V_MODEL_SEEDANCE)
            model_label = MODEL_DISPLAY_NAMES.get(i2v_model, i2v_model)
            summary += f"Модель: {model_label}\n"
        summary += (
            f"Формат: {data.get('aspect_ratio', '16:9')}\n"
            f"Длительность: {data.get('duration', '5')} сек\n"
            f"Качество: {data.get('resolution', '720p')}\n"
            f"Аудио: {'✅' if data.get('generate_audio') else '❌'}\n"
        )

    summary += f"\n📝 Промпт:\n{prompt[:200]}"
    return summary


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
    summary = _build_summary(data, prompt)

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

    # Store enhanced prompt in state
    await state.update_data(enhanced_prompt=enhanced_prompt)

    # Show both options
    await callback.message.edit_text(
        f"✨ Улучшение промпта:\n\n"
        f"📝 Оригинал:\n{original_prompt}\n\n"
        f"✨ Улучшенный AI:\n{enhanced_prompt}",
        parse_mode=None,
        reply_markup=_get_enhanced_prompt_keyboard(),
    )


@router.callback_query(F.data == "video_use_original")
async def callback_use_original(callback: CallbackQuery, state: FSMContext) -> None:
    """Use original prompt."""
    data = await state.get_data()
    original_prompt = data.get("prompt", "")

    await state.set_state(VideoWizard.confirm)

    await callback.message.edit_text(
        f"✅ Выбран оригинальный промпт:\n\n{original_prompt[:200]}",
        parse_mode=None,
        reply_markup=_get_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "video_use_enhanced")
async def callback_use_enhanced(callback: CallbackQuery, state: FSMContext) -> None:
    """Use enhanced prompt."""
    data = await state.get_data()
    enhanced_prompt = data.get("enhanced_prompt", "")

    await state.update_data(prompt=enhanced_prompt)
    await state.set_state(VideoWizard.confirm)

    await callback.message.edit_text(
        f"✅ Выбран улучшенный промпт:\n\n{enhanced_prompt[:200]}",
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

        # Translate prompt to English for Seedance API
        api_prompt = await _translate_to_english(prompt)

        status_msg = callback.message
        await status_msg.edit_text(_PROGRESS_FRAMES[0], parse_mode=None)

        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(
            _run_progress(bot, callback.message.chat.id, status_msg, stop_event)
        )

        try:
            if mode == MODE_IMAGE_TO_VIDEO:
                image_bytes = data.get("image_data")
                if not image_bytes:
                    stop_event.set()
                    await progress_task
                    await status_msg.edit_text(
                        "❌ Ошибка: изображение не найдено", parse_mode=None
                    )
                    return

                image_url = await upload_image_to_fal(image_bytes, "input.jpg")

                if not image_url.startswith("http"):
                    stop_event.set()
                    await progress_task
                    await status_msg.edit_text(f"❌ {image_url}", parse_mode=None)
                    return

                i2v_model = data.get("i2v_model", I2V_MODEL_SEEDANCE)

                if i2v_model == I2V_MODEL_KLING:
                    sound = "on" if generate_audio else "off"
                    result = await generate_i2v_kling(
                        prompt=api_prompt,
                        image_url=image_url,
                        duration=duration,
                        quality=resolution,
                        aspect_ratio=aspect_ratio,
                        sound=sound,
                    )
                else:
                    result = await generate_video_from_image(
                        prompt=api_prompt,
                        image_url=image_url,
                        duration=duration,
                        resolution=resolution,
                        aspect_ratio=aspect_ratio,
                        generate_audio=generate_audio,
                    )

            elif mode == MODE_VIDEO_TO_VIDEO:
                source_video_url = data.get("source_video_url")
                if not source_video_url:
                    stop_event.set()
                    await progress_task
                    await status_msg.edit_text(
                        "❌ Ошибка: исходное видео не найдено", parse_mode=None
                    )
                    return

                v2v_model = data.get("v2v_model", V2V_MODEL_WAN)

                if v2v_model == V2V_MODEL_WAN:
                    result = await generate_v2v_wan(
                        prompt=api_prompt,
                        video_url=source_video_url,
                        strength=data.get("v2v_strength", 0.6),
                        resolution=resolution,
                    )
                else:
                    result = await generate_v2v_kling(
                        prompt=api_prompt,
                        video_url=source_video_url,
                        quality=resolution,
                        keep_audio=generate_audio,
                    )

            else:
                result = await generate_video(
                    prompt=api_prompt,
                    duration=duration,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    generate_audio=generate_audio,
                )

            stop_event.set()
            await progress_task

            if isinstance(result, str):
                await status_msg.edit_text(f"❌ {result}", parse_mode=None)
                return

            await _send_video(
                callback.message, result, prompt, state, status_msg,
                user_id=user_id,
            )

        except Exception as e:
            stop_event.set()
            await progress_task
            logger.error(f"Video generation error: {e}", exc_info=True)
            await status_msg.edit_text(
                f"❌ Ошибка генерации: {e}", parse_mode=None
            )
