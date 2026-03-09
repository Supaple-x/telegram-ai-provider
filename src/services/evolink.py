import asyncio
import logging
from typing import Any

import httpx

from config.settings import settings
from src.database.service_status import set_balance_ok

logger = logging.getLogger(__name__)

# EvoLink API
API_BASE = "https://api.evolink.ai"
GENERATIONS_ENDPOINT = f"{API_BASE}/v1/videos/generations"
TASKS_ENDPOINT = f"{API_BASE}/v1/tasks"

# Model slugs
KLING_O3_VIDEO_EDIT = "kling-o3-video-edit"
KLING_O3_I2V = "kling-o3-image-to-video"

# Polling settings
POLL_INTERVAL = 10.0  # seconds (EvoLink processing takes 180-300s)
POLL_TIMEOUT = 600.0  # 10 minutes max

# Balance tracking (resets on restart)
_balance_ok = True


def is_available() -> bool:
    """Check if EvoLink has key and no known billing issues."""
    return bool(settings.evolink_api_key) and _balance_ok


def mark_balance_exhausted() -> None:
    """Mark EvoLink as having exhausted balance (in-memory + DB)."""
    global _balance_ok
    _balance_ok = False
    logger.warning("EvoLink marked as balance exhausted")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_balance("evolink", False))
    except RuntimeError:
        pass


async def _persist_balance(service: str, ok: bool) -> None:
    """Persist balance status to DB (fire-and-forget)."""
    try:
        await set_balance_ok(service, ok)
    except Exception as e:
        logger.warning(f"Failed to persist balance status: {e}")


def init_evolink_client() -> bool:
    """
    Check if EvoLink client is configured.

    Returns:
        True if API key is set, False otherwise
    """
    if settings.evolink_api_key:
        logger.info("EvoLink client initialized (Kling O3 video-edit)")
        return True
    else:
        logger.warning("EVOLINK_API_KEY not set, Kling O3 video-edit disabled")
        return False


def get_evolink_client() -> bool:
    """Check if EvoLink client is available."""
    return bool(settings.evolink_api_key)


def _get_headers() -> dict[str, str]:
    """Get authorization headers."""
    return {
        "Authorization": f"Bearer {settings.evolink_api_key}",
        "Content-Type": "application/json",
    }


async def generate_v2v_kling(
    prompt: str,
    video_url: str,
    quality: str = "720p",
    keep_audio: bool = True,
) -> dict[str, Any] | str:
    """
    Generate video-to-video using Kling O3 via EvoLink.

    Note: output video preserves input dimensions and duration.

    Args:
        prompt: Text description of desired transformation (max 2500 chars)
        video_url: Public URL of source video (MP4/MOV, max 200MB)
        quality: Output quality ("720p" | "1080p")
        keep_audio: Whether to preserve original audio

    Returns:
        Dict with {"url": str} or error message string
    """
    if not settings.evolink_api_key:
        return "Kling O3 не настроен (отсутствует EVOLINK_API_KEY)"

    payload = {
        "model": KLING_O3_VIDEO_EDIT,
        "prompt": prompt[:2500],
        "video_url": video_url,
        "quality": quality,
        "keep_original_sound": keep_audio,
    }

    logger.info(f"Calling Kling O3 video-edit ({quality}): {prompt[:50]}...")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GENERATIONS_ENDPOINT,
                headers=_get_headers(),
                json=payload,
            )

            if response.status_code != 200:
                error_msg = _parse_error_response(response)
                if response.status_code == 402:
                    mark_balance_exhausted()
                return error_msg

            data = response.json()
            task_id = data.get("id")

            if not task_id:
                logger.error(f"No task_id in EvoLink response: {data}")
                return "Ошибка: не удалось создать задачу"

            estimated = data.get("task_info", {}).get("estimated_time", "?")
            logger.info(f"EvoLink task created: {task_id}, estimated: {estimated}s")

        # Poll for result
        return await _poll_evolink_task(task_id)

    except httpx.TimeoutException:
        return "Превышено время ожидания ответа от EvoLink"
    except Exception as e:
        logger.error(f"EvoLink API error: {e}", exc_info=True)
        return f"Ошибка генерации видео: {e}"


async def generate_i2v_kling(
    prompt: str,
    image_url: str,
    duration: str = "5",
    quality: str = "720p",
    aspect_ratio: str = "16:9",
    sound: str = "off",
) -> dict[str, Any] | str:
    """
    Generate image-to-video using Kling O3 via EvoLink.

    Args:
        prompt: Text description of motion/action (max 2500 chars)
        image_url: Public URL of source image
        duration: Video duration ("5" | "10")
        quality: Output quality ("720p" | "1080p")
        aspect_ratio: Aspect ratio ("16:9" | "9:16" | "1:1")
        sound: Audio generation ("on" | "off")

    Returns:
        Dict with {"url": str} or error message string
    """
    if not settings.evolink_api_key:
        return "Kling O3 не настроен (отсутствует EVOLINK_API_KEY)"

    payload = {
        "model": KLING_O3_I2V,
        "prompt": prompt[:2500],
        "image_urls": [image_url],
        "duration": int(duration),
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "sound": sound,
    }

    logger.info(f"Calling Kling O3 i2v ({quality}, {duration}s): {prompt[:50]}...")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GENERATIONS_ENDPOINT,
                headers=_get_headers(),
                json=payload,
            )

            if response.status_code != 200:
                error_msg = _parse_error_response(response)
                if response.status_code == 402:
                    mark_balance_exhausted()
                return error_msg

            data = response.json()
            task_id = data.get("id")

            if not task_id:
                logger.error(f"No task_id in EvoLink response: {data}")
                return "Ошибка: не удалось создать задачу"

            estimated = data.get("task_info", {}).get("estimated_time", "?")
            logger.info(f"EvoLink i2v task created: {task_id}, estimated: {estimated}s")

        return await _poll_evolink_task(task_id)

    except httpx.TimeoutException:
        return "Превышено время ожидания ответа от EvoLink"
    except Exception as e:
        logger.error(f"EvoLink API error: {e}", exc_info=True)
        return f"Ошибка генерации видео: {e}"


async def _poll_evolink_task(task_id: str) -> dict[str, Any] | str:
    """
    Poll EvoLink task until completion.

    Returns:
        Dict with {"url": str} or error message string
    """
    poll_url = f"{TASKS_ENDPOINT}/{task_id}"
    headers = {"Authorization": f"Bearer {settings.evolink_api_key}"}
    elapsed = 0.0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            try:
                response = await client.get(poll_url, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"Poll error {response.status_code}: {response.text[:200]}")
                    continue

                data = response.json()
                status = data.get("status", "")
                progress = data.get("progress", 0)

                if status == "completed":
                    results = data.get("results", [])
                    if results:
                        video_url = results[0]
                        logger.info(f"Kling O3 video-edit completed: {video_url}")
                        return {"url": video_url}
                    return "Не удалось получить видео от Kling O3"

                elif status == "failed":
                    logger.error(f"EvoLink task failed: {data}")
                    return "Ошибка генерации видео Kling O3"

                logger.debug(f"EvoLink task {task_id}: {status} ({progress}%)")

            except httpx.TimeoutException:
                logger.warning("Poll timeout, retrying...")
                continue
            except Exception as e:
                logger.warning(f"Poll error: {e}")
                continue

    return "Превышено время ожидания генерации видео"


def _parse_error_response(response: httpx.Response) -> str:
    """Parse error response from EvoLink."""
    status = response.status_code
    try:
        data = response.json()
        error_type = data.get("error", {}).get("type", "")
        message = data.get("error", {}).get("message", "") or str(data)
    except Exception:
        error_type = ""
        message = response.text[:200]

    logger.error(f"EvoLink error {status} ({error_type}): {message}")

    if status == 401:
        return "Неверный EVOLINK_API_KEY"
    elif status == 402 or error_type == "insufficient_quota_error":
        return (
            "Баланс EvoLink исчерпан.\n\n"
            "Генерация видео временно недоступна. "
            "Администратору необходимо пополнить баланс на evolink.ai"
        )
    elif status == 429:
        return "Превышен лимит запросов EvoLink. Попробуйте позже."
    elif status == 400 or status == 422:
        return f"Ошибка в параметрах: {message}"

    return f"Ошибка EvoLink ({status}): {message}"
