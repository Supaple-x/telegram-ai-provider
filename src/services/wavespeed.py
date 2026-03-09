import asyncio
import logging
from typing import Any

import httpx

from config.settings import settings
from src.database.service_status import set_balance_ok

logger = logging.getLogger(__name__)

# WaveSpeedAI API
API_BASE = "https://api.wavespeed.ai/api/v3"
UPLOAD_ENDPOINT = f"{API_BASE}/media/upload/binary"

# Model endpoints by resolution
WAN_V2V_MODELS = {
    "480p": "wavespeed-ai/wan-2.2/v2v-480p-ultra-fast",
    "720p": "wavespeed-ai/wan-2.2/v2v-720p-ultra-fast",
}

# Polling settings
POLL_INTERVAL = 5.0  # seconds
POLL_TIMEOUT = 600.0  # 10 minutes max

# Balance tracking (resets on restart)
_balance_ok = True


def is_available() -> bool:
    """Check if WaveSpeedAI has key and no known billing issues."""
    return bool(settings.wavespeed_api_key) and _balance_ok


def mark_balance_exhausted() -> None:
    """Mark WaveSpeedAI as having exhausted balance (in-memory + DB)."""
    global _balance_ok
    _balance_ok = False
    logger.warning("WaveSpeedAI marked as balance exhausted")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_balance("wavespeed", False))
    except RuntimeError:
        pass


async def _persist_balance(service: str, ok: bool) -> None:
    """Persist balance status to DB (fire-and-forget)."""
    try:
        await set_balance_ok(service, ok)
    except Exception as e:
        logger.warning(f"Failed to persist balance status: {e}")


def init_wavespeed_client() -> bool:
    """
    Check if WaveSpeedAI client is configured.

    Returns:
        True if API key is set, False otherwise
    """
    if settings.wavespeed_api_key:
        logger.info("WaveSpeedAI client initialized (Wan 2.2 v2v)")
        return True
    else:
        logger.warning("WAVESPEED_API_KEY not set, Wan 2.2 v2v disabled")
        return False


def get_wavespeed_client() -> bool:
    """Check if WaveSpeedAI client is available."""
    return bool(settings.wavespeed_api_key)


def _get_headers() -> dict[str, str]:
    """Get authorization headers."""
    return {
        "Authorization": f"Bearer {settings.wavespeed_api_key}",
        "Content-Type": "application/json",
    }


async def upload_video_to_wavespeed(
    video_bytes: bytes,
    filename: str = "input.mp4",
) -> str:
    """
    Upload video to WaveSpeedAI storage.

    Args:
        video_bytes: Video data as bytes
        filename: Filename with extension

    Returns:
        Public URL of uploaded video or error message string
    """
    if not settings.wavespeed_api_key:
        return "WaveSpeedAI не настроен (отсутствует WAVESPEED_API_KEY)"

    try:
        logger.info(f"Uploading video {filename} ({len(video_bytes)} bytes) to WaveSpeedAI...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                UPLOAD_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.wavespeed_api_key}"},
                files={"file": (filename, video_bytes, "video/mp4")},
            )

            if response.status_code != 200:
                return _parse_error_response(response)

            data = response.json()
            url = data.get("data", {}).get("download_url", "")

            if not url:
                logger.error(f"No download_url in upload response: {data}")
                return "Ошибка загрузки видео: пустой URL"

            logger.info(f"Video uploaded to WaveSpeedAI: {url}")
            return url

    except httpx.TimeoutException:
        return "Превышено время загрузки видео"
    except Exception as e:
        logger.error(f"WaveSpeedAI upload error: {e}", exc_info=True)
        return f"Ошибка загрузки видео: {e}"


async def generate_v2v_wan(
    prompt: str,
    video_url: str,
    strength: float = 0.6,
    resolution: str = "720p",
    duration: int = 5,
) -> dict[str, Any] | str:
    """
    Generate video-to-video using Wan 2.2 via WaveSpeedAI.

    Args:
        prompt: Text description of desired transformation
        video_url: Public URL of source video
        strength: Transformation strength (0.1-1.0)
        resolution: Output resolution ("480p" | "720p")
        duration: Output duration in seconds (5-10)

    Returns:
        Dict with {"url": str} or error message string
    """
    if not settings.wavespeed_api_key:
        return "Wan 2.2 не настроен (отсутствует WAVESPEED_API_KEY)"

    model = WAN_V2V_MODELS.get(resolution, WAN_V2V_MODELS["720p"])
    endpoint = f"{API_BASE}/{model}"

    payload = {
        "video": video_url,
        "prompt": prompt,
        "strength": strength,
        "duration": duration,
        "num_inference_steps": 30,
        "guidance_scale": 5,
        "seed": -1,
    }

    logger.info(f"Calling Wan 2.2 V2V ({resolution}): {prompt[:50]}...")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Submit task
            response = await client.post(
                endpoint,
                headers=_get_headers(),
                json=payload,
            )

            if response.status_code != 200:
                return _parse_error_response(response)

            data = response.json()
            task_id = data.get("data", {}).get("id")

            if not task_id:
                logger.error(f"No task_id in WaveSpeedAI response: {data}")
                return "Ошибка: не удалось создать задачу"

            logger.info(f"WaveSpeedAI task created: {task_id}")

        # Step 2: Poll for result
        return await _poll_wavespeed_task(task_id)

    except httpx.TimeoutException:
        return "Превышено время ожидания ответа от WaveSpeedAI"
    except Exception as e:
        logger.error(f"WaveSpeedAI API error: {e}", exc_info=True)
        return f"Ошибка генерации видео: {e}"


async def _poll_wavespeed_task(task_id: str) -> dict[str, Any] | str:
    """
    Poll WaveSpeedAI task until completion.

    Returns:
        Dict with {"url": str} or error message string
    """
    poll_url = f"{API_BASE}/predictions/{task_id}"
    headers = {"Authorization": f"Bearer {settings.wavespeed_api_key}"}
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

                data = response.json().get("data", {})
                status = data.get("status", "")

                if status == "completed":
                    outputs = data.get("outputs", [])
                    if outputs:
                        video_url = outputs[0]
                        logger.info(f"Wan 2.2 V2V completed: {video_url}")
                        return {"url": video_url}
                    return "Не удалось получить видео от Wan 2.2"

                elif status == "failed":
                    error = data.get("error", "unknown error")
                    logger.error(f"WaveSpeedAI task failed: {error}")
                    return f"Ошибка генерации: {error}"

                logger.debug(f"WaveSpeedAI task {task_id}: {status}")

            except httpx.TimeoutException:
                logger.warning("Poll timeout, retrying...")
                continue
            except Exception as e:
                logger.warning(f"Poll error: {e}")
                continue

    return "Превышено время ожидания генерации видео"


def _parse_error_response(response: httpx.Response) -> str:
    """Parse error response from WaveSpeedAI."""
    status = response.status_code
    try:
        data = response.json()
        message = data.get("message", "") or data.get("error", "")
    except Exception:
        message = response.text[:200]

    logger.error(f"WaveSpeedAI error {status}: {message}")

    if status == 401:
        return "Неверный WAVESPEED_API_KEY"
    elif status == 402 or "balance" in message.lower() or "credit" in message.lower():
        mark_balance_exhausted()
        return (
            "Баланс WaveSpeedAI исчерпан.\n\n"
            "Генерация видео временно недоступна. "
            "Администратору необходимо пополнить баланс на wavespeed.ai"
        )
    elif status == 429:
        return "Превышен лимит запросов WaveSpeedAI. Попробуйте позже."
    elif status == 422:
        return f"Ошибка в параметрах: {message}"

    return f"Ошибка WaveSpeedAI ({status}): {message}"
