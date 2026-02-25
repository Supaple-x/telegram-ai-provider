import logging

from aiogram import Router, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command, CommandObject
from aiogram.enums import ChatAction

from src.services.image_gen import generate_image, edit_image, get_image_client

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("imagine"))
async def cmd_imagine(message: Message, command: CommandObject, bot: Bot) -> None:
    """Generate image from text prompt using Imagen 4."""
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
            "🎨 Генерация изображений с Imagen 4\n\n"
            "Использование:\n"
            "/imagine <описание изображения>\n\n"
            "Примеры:\n"
            "• /imagine a cute astronaut kitten on the Moon\n"
            "• /imagine minimalist coffee shop logo\n"
            "• /imagine Swiss mountain landscape at sunset\n\n"
            "💡 Лучше использовать промпты на английском языке.",
            parse_mode=None,
        )
        return

    prompt = command.args
    logger.info(f"Generating image for prompt: {prompt[:50]}...")

    # Show generating status
    status_msg = await message.answer("🎨 Генерирую изображение...", parse_mode=None)
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    # Generate image
    logger.info("Calling generate_image...")
    result = await generate_image(prompt)
    logger.info(f"generate_image returned: {type(result)}")

    # Delete status message
    await status_msg.delete()

    if isinstance(result, str):
        # Error message - send without markdown
        await message.answer(f"❌ {result}", parse_mode=None)
        return

    image_bytes, mime_type = result

    # Determine file extension
    ext = "png" if "png" in mime_type else "jpg"
    filename = f"generated.{ext}"

    # Send image
    photo = BufferedInputFile(image_bytes, filename=filename)
    await message.answer_photo(
        photo,
        caption=f"🎨 {prompt[:200]}\n\nImagen 4",
        parse_mode=None,
    )


@router.message(Command("edit"))
async def cmd_edit(message: Message, command: CommandObject, bot: Bot) -> None:
    """Edit image - currently disabled."""
    await message.answer(
        "🖌 Редактирование изображений временно недоступно.\n"
        "Используйте /imagine для генерации новых изображений.",
        parse_mode=None,
    )
