import logging

from aiogram import Router, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, CommandObject
from aiogram.enums import ChatAction

from src.services.image_gen import generate_image, edit_image, get_image_client

logger = logging.getLogger(__name__)
router = Router()

# Max file size for image editing (Telegram photos)
_MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB


@router.message(Command("imagine"))
async def cmd_imagine(message: Message, command: CommandObject, bot: Bot) -> None:
    """Generate or edit image using Nano Banana."""
    logger.info(f"Received /imagine command from user {message.from_user.id}")

    if not get_image_client():
        logger.warning("Image client not initialized")
        await message.answer(
            "❌ Генерация изображений не настроена.\n"
            "Администратору необходимо добавить GEMINI_API_KEY.",
            parse_mode=None,
        )
        return

    if not command.args:
        await message.answer(
            "🎨 Генерация изображений с Nano Banana\n\n"
            "Использование:\n"
            "/imagine <описание изображения>\n\n"
            "Редактирование фото:\n"
            "• Ответьте на фото командой /imagine <что изменить>\n"
            "• Или отправьте фото с подписью /imagine <что изменить>\n\n"
            "Примеры:\n"
            "• /imagine a cute astronaut kitten on the Moon\n"
            "• /imagine логотип кофейни в минималистичном стиле\n"
            "• (в ответ на фото) /imagine сделай в стиле аниме\n\n"
            "💡 Поддерживает русский и английский.\n"
            "Умеет рисовать текст на изображениях!",
            parse_mode=None,
        )
        return

    prompt = command.args

    # Check if there's a source photo (reply to photo or photo with caption)
    source_photo = None

    # Photo sent with /imagine caption
    if message.photo:
        source_photo = message.photo[-1]

    # Reply to a message with photo
    elif message.reply_to_message and message.reply_to_message.photo:
        source_photo = message.reply_to_message.photo[-1]

    if source_photo:
        await _handle_edit(message, bot, prompt, source_photo)
    else:
        await _handle_generate(message, bot, prompt)


async def _handle_generate(message: Message, bot: Bot, prompt: str) -> None:
    """Generate image from text prompt."""
    logger.info(f"Generating image for prompt: {prompt[:50]}...")

    status_msg = await message.answer("🎨 Генерирую изображение...", parse_mode=None)
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    result = await generate_image(prompt)

    await status_msg.delete()

    if isinstance(result, str):
        await message.answer(f"❌ {result}", parse_mode=None)
        return

    image_bytes, mime_type = result
    ext = "png" if "png" in mime_type else "jpg"
    photo = BufferedInputFile(image_bytes, filename=f"generated.{ext}")
    await message.answer_photo(
        photo,
        caption=f"🎨 {prompt[:200]}\n\nNano Banana",
        parse_mode=None,
    )


async def _handle_edit(message: Message, bot: Bot, prompt: str, photo) -> None:
    """Edit existing photo with text prompt."""
    logger.info(f"Editing image with prompt: {prompt[:50]}...")

    status_msg = await message.answer("🖌 Редактирую изображение...", parse_mode=None)
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    # Download source photo
    file = await bot.get_file(photo.file_id)
    photo_io = await bot.download_file(file.file_path)
    image_bytes = photo_io.read()

    result = await edit_image(prompt, image_bytes, "image/jpeg")

    await status_msg.delete()

    if isinstance(result, str):
        await message.answer(f"❌ {result}", parse_mode=None)
        return

    result_bytes, mime_type = result
    ext = "png" if "png" in mime_type else "jpg"
    photo_file = BufferedInputFile(result_bytes, filename=f"edited.{ext}")
    await message.answer_photo(
        photo_file,
        caption=f"🖌 {prompt[:200]}\n\nNano Banana (edit)",
        parse_mode=None,
    )
