import logging
from typing import Any

from src.database.connection import get_pool

logger = logging.getLogger(__name__)


async def add_video_generation(
    telegram_id: int,
    prompt: str,
    mode: str = "text-to-video",
    duration: str = "5",
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    video_url: str | None = None,
    seed: int | None = None,
) -> int:
    """
    Add video generation record to database.

    Args:
        telegram_id: Telegram user ID
        prompt: Video prompt text
        mode: 'text-to-video' or 'image-to-video'
        duration: Video duration ("5" | "8" | "10")
        resolution: Video resolution ("720p" | "1080p")
        aspect_ratio: Aspect ratio ("16:9" | "9:16" | "1:1" | "4:3" | "3:4")
        video_url: URL of generated video
        seed: Random seed used for generation

    Returns:
        ID of created record
    """
    pool = get_pool()
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO video_generations (
                user_id, prompt, mode, duration, resolution, aspect_ratio, video_url, seed
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            telegram_id,
            prompt,
            mode,
            duration,
            resolution,
            aspect_ratio,
            video_url,
            seed,
        )
        
        logger.info(f"Added video generation record: id={row['id']}, user={telegram_id}")
        return row["id"]


async def update_video_url(record_id: int, video_url: str) -> None:
    """
    Update video URL for existing record.

    Args:
        record_id: Record ID to update
        video_url: URL of generated video
    """
    pool = get_pool()
    
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE video_generations
            SET video_url = $2
            WHERE id = $1
            """,
            record_id,
            video_url,
        )
        
        logger.info(f"Updated video URL for record {record_id}")


async def get_user_video_history(
    telegram_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Get user's video generation history.

    Args:
        telegram_id: Telegram user ID
        limit: Maximum number of records to return

    Returns:
        List of video generation records (newest first)
    """
    pool = get_pool()
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, prompt, mode, duration, resolution, aspect_ratio, video_url, seed, created_at
            FROM video_generations
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            telegram_id,
            limit,
        )
        
        return [dict(row) for row in rows]


async def get_video_generation(record_id: int) -> dict[str, Any] | None:
    """
    Get single video generation record by ID.

    Args:
        record_id: Record ID to retrieve

    Returns:
        Video generation record or None if not found
    """
    pool = get_pool()
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, prompt, mode, duration, resolution, aspect_ratio, video_url, seed, created_at
            FROM video_generations
            WHERE id = $1
            """,
            record_id,
        )
        
        return dict(row) if row else None
