"""Tests for src.database.context — add_message with image_data, get_context with images."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database.context import MAX_CONTEXT_IMAGES


def _mock_pool(conn):
    """Create a mocked asyncpg pool with given connection."""
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


class TestAddMessageWithImage:
    @pytest.mark.asyncio
    async def test_add_message_no_image(self):
        """Without image_data, only messages INSERT is called."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock()

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            from src.database.context import add_message
            await add_message(111, "user", "Hello")

        conn.execute.assert_called_once()
        assert "messages" in conn.execute.call_args[0][0]
        conn.fetchval.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_message_with_image(self):
        """With image_data, both messages and attachments are inserted in transaction."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.fetchval = AsyncMock(return_value=42)
        conn.transaction = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            from src.database.context import add_message
            await add_message(111, "user", "[Изображение] Что это?",
                              image_data=("base64data", "image/jpeg"))

        # Should use RETURNING id
        conn.fetchval.assert_called_once()
        assert "RETURNING id" in conn.fetchval.call_args[0][0]
        # Should insert attachment
        conn.execute.assert_called_once()
        assert "message_attachments" in conn.execute.call_args[0][0]
        assert conn.execute.call_args[0][1] == 42  # message_id
        assert conn.execute.call_args[0][2] == "base64data"
        assert conn.execute.call_args[0][3] == "image/jpeg"


class TestGetContextWithImages:
    @pytest.mark.asyncio
    async def test_returns_image_data_for_messages_with_attachments(self):
        """Messages with attachments include image_data tuple."""
        rows = [
            # DESC order (newest first)
            {"role": "user", "content": "Какого цвета?",
             "image_base64": None, "media_type": None},
            {"role": "assistant", "content": "Это кот.",
             "image_base64": None, "media_type": None},
            {"role": "user", "content": "[Изображение] Что это?",
             "image_base64": "img_b64", "media_type": "image/jpeg"},
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            with patch("src.database.context.settings") as mock_s:
                mock_s.max_context_messages = 20
                from src.database.context import get_context
                result = await get_context(999)

        # Chronological order (reversed)
        assert len(result) == 3
        assert result[0]["content"] == "[Изображение] Что это?"
        assert result[0]["image_data"] == ("img_b64", "image/jpeg")
        assert "image_data" not in result[1]
        assert "image_data" not in result[2]

    @pytest.mark.asyncio
    async def test_limits_images_to_max(self):
        """Only MAX_CONTEXT_IMAGES most recent images are included."""
        # 5 image messages, newest first
        rows = [
            {"role": "user", "content": f"Фото {5 - i}",
             "image_base64": f"img_{5 - i}", "media_type": "image/jpeg"}
            for i in range(5)
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            with patch("src.database.context.settings") as mock_s:
                mock_s.max_context_messages = 20
                from src.database.context import get_context
                result = await get_context(999)

        # Should have exactly MAX_CONTEXT_IMAGES images
        images_in_result = [m for m in result if "image_data" in m]
        assert len(images_in_result) == MAX_CONTEXT_IMAGES

        # Most recent images (rows[0], [1], [2] = Фото 5, 4, 3) should be kept
        # In chronological order, these are the LAST entries
        assert result[-1].get("image_data") is not None
        assert result[-2].get("image_data") is not None
        assert result[-3].get("image_data") is not None
        # Oldest two should NOT have image_data
        assert "image_data" not in result[0]
        assert "image_data" not in result[1]

    @pytest.mark.asyncio
    async def test_no_images_in_context(self):
        """Messages without attachments have no image_data key."""
        rows = [
            {"role": "assistant", "content": "Hi",
             "image_base64": None, "media_type": None},
            {"role": "user", "content": "Hello",
             "image_base64": None, "media_type": None},
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            with patch("src.database.context.settings") as mock_s:
                mock_s.max_context_messages = 20
                from src.database.context import get_context
                result = await get_context(999)

        assert len(result) == 2
        assert "image_data" not in result[0]
        assert "image_data" not in result[1]

    @pytest.mark.asyncio
    async def test_chronological_order(self):
        """Results are returned in chronological order."""
        rows = [
            {"role": "user", "content": "Third",
             "image_base64": None, "media_type": None},
            {"role": "assistant", "content": "Second",
             "image_base64": None, "media_type": None},
            {"role": "user", "content": "First",
             "image_base64": None, "media_type": None},
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.database.context.get_pool", return_value=_mock_pool(conn)):
            with patch("src.database.context.settings") as mock_s:
                mock_s.max_context_messages = 20
                from src.database.context import get_context
                result = await get_context(999)

        assert [m["content"] for m in result] == ["First", "Second", "Third"]


class TestMaxContextImages:
    def test_constant_value(self):
        """MAX_CONTEXT_IMAGES is 3."""
        assert MAX_CONTEXT_IMAGES == 3
