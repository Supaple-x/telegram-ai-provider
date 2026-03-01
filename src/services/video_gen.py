import asyncio
import logging
from typing import Any

import fal_client

from config.settings import settings

logger = logging.getLogger(__name__)

# Seedance 1.5 Pro endpoints
TEXT_TO_VIDEO_ENDPOINT = "fal-ai/bytedance/seedance/v1.5/pro/text-to-video"
IMAGE_TO_VIDEO_ENDPOINT = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds


def init_video_client() -> bool:
    """
    Initialize fal.ai client for video generation.
    
    Returns:
        True if initialized successfully, False otherwise
    """
    if settings.fal_api_key:
        # fal-client reads FAL_KEY from env automatically,
        # but we verify it's set
        logger.info(f"fal.ai client initialized ({settings.seedance_model})")
        return True
    else:
        logger.warning("FAL_KEY not set, video generation disabled")
        return False


def get_video_client() -> bool:
    """
    Check if video client is available.
    
    Returns:
        True if client is initialized, False otherwise
    """
    return bool(settings.fal_api_key)


async def upload_image_to_fal(image_bytes: bytes, filename: str) -> str:
    """
    Upload image to fal.ai storage and get public URL.
    
    Args:
        image_bytes: Image data as bytes
        filename: Filename with extension (e.g., "image.jpg")
        
    Returns:
        Public URL of uploaded image or error message string
    """
    if not settings.fal_api_key:
        return "fal.ai не настроен (отсутствует FAL_KEY)"
    
    try:
        logger.info(f"Uploading image {filename} to fal.storage...")
        
        # Run sync upload in thread pool
        url = await asyncio.to_thread(
            fal_client.upload,
            filename,
            image_bytes
        )
        
        logger.info(f"Image uploaded successfully: {url}")
        return url
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Image upload error: {error_msg}", exc_info=True)
        
        if "authentication" in error_msg.lower() or "401" in error_msg:
            return "Неверный FAL_KEY"
        elif "rate limit" in error_msg.lower() or "429" in error_msg:
            return "Превышен лимит загрузки файлов"
        
        return f"Ошибка загрузки изображения: {error_msg}"


async def generate_video(
    prompt: str,
    duration: str = "5",
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    generate_audio: bool = True,
) -> dict[str, Any] | str:
    """
    Generate video from text prompt using Seedance 1.5 Pro.
    
    Args:
        prompt: Text description of the video
        duration: Video duration ("5" | "8" | "10")
        resolution: Video resolution ("720p" | "1080p")
        aspect_ratio: Aspect ratio ("16:9" | "9:16" | "1:1" | "4:3" | "3:4")
        generate_audio: Whether to generate audio with lip-sync
        
    Returns:
        Dict with {"url": str, "seed": int} or error message string
    """
    if not settings.fal_api_key:
        return "Генерация видео не настроена (отсутствует FAL_KEY)"
    
    arguments = {
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
        "enable_safety_checker": True,
    }
    
    logger.info(f"Calling Seedance API: {prompt[:50]}...")
    
    return await _call_seedance_api(TEXT_TO_VIDEO_ENDPOINT, arguments)


async def generate_video_from_image(
    prompt: str,
    image_url: str,
    duration: str = "5",
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    generate_audio: bool = True,
) -> dict[str, Any] | str:
    """
    Generate video from image using Seedance 1.5 Pro (image-to-video).
    
    Args:
        prompt: Text description of motion/action
        image_url: Public URL of the source image
        duration: Video duration ("5" | "8" | "10")
        resolution: Video resolution ("720p" | "1080p")
        aspect_ratio: Aspect ratio ("16:9" | "9:16" | "1:1" | "4:3" | "3:4")
        generate_audio: Whether to generate audio with lip-sync
        
    Returns:
        Dict with {"url": str, "seed": int} or error message string
    """
    if not settings.fal_api_key:
        return "Генерация видео не настроена (отсутствует FAL_KEY)"
    
    arguments = {
        "prompt": prompt,
        "image_url": image_url,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
        "enable_safety_checker": True,
    }
    
    logger.info(f"Calling Seedance image-to-video API: {prompt[:50]}...")
    
    return await _call_seedance_api(IMAGE_TO_VIDEO_ENDPOINT, arguments)


async def _call_seedance_api(
    endpoint: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | str:
    """
    Call Seedance API with retry logic.
    
    Args:
        endpoint: API endpoint (text-to-video or image-to-video)
        arguments: API arguments
        
    Returns:
        Dict with video result or error message string
    """
    retry_count = 0
    
    while retry_count < MAX_RETRIES:
        try:
            # Run sync subscribe in thread pool (takes 30-120 seconds)
            result = await asyncio.to_thread(
                fal_client.subscribe,
                endpoint,
                arguments=arguments
            )
            
            if result and "video" in result and "url" in result["video"]:
                video_url = result["video"]["url"]
                seed = result.get("seed", 0)
                
                logger.info(f"Video generated successfully: {video_url}, seed={seed}")
                
                return {"url": video_url, "seed": seed}
            
            logger.error(f"Unexpected API response: {result}")
            return "Не удалось получить видео от Seedance"
            
        except fal_client.RateLimitError:
            retry_count += 1
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_BACKOFF * (2 ** (retry_count - 1))
                logger.warning(f"Rate limit hit, retrying in {wait_time}s... ({retry_count}/{MAX_RETRIES})")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Rate limit exceeded after retries")
                return "Превышен лимит запросов. Попробуйте позже."
                
        except fal_client.AuthenticationError:
            logger.error("Authentication failed", exc_info=True)
            return "Неверный FAL_KEY"
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Seedance API error: {error_msg}", exc_info=True)
            
            # Don't retry on validation errors
            if "validation" in error_msg.lower() or "invalid" in error_msg.lower():
                return f"Ошибка в параметрах: {error_msg}"
            
            retry_count += 1
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_BACKOFF * (2 ** (retry_count - 1))
                logger.warning(f"Error occurred, retrying in {wait_time}s... ({retry_count}/{MAX_RETRIES})")
                await asyncio.sleep(wait_time)
            else:
                return f"Ошибка генерации видео: {error_msg}"
    
    return "Ошибка генерации видео: превышено количество попыток"
