"""Tests for EvoLink service (Kling O3 video-to-video and image-to-video)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.evolink import (
    generate_i2v_kling,
    generate_v2v_kling,
    get_evolink_client,
    init_evolink_client,
    is_available,
)


class TestEvolinkClient:
    """Tests for EvoLink client initialization."""

    def test_init_with_key(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"
        with patch("src.services.evolink.settings", mock_settings):
            assert init_evolink_client() is True

    def test_init_without_key(self, mock_settings):
        mock_settings.evolink_api_key = ""
        with patch("src.services.evolink.settings", mock_settings):
            assert init_evolink_client() is False

    def test_get_client_with_key(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"
        with patch("src.services.evolink.settings", mock_settings):
            assert get_evolink_client() is True

    def test_get_client_without_key(self, mock_settings):
        mock_settings.evolink_api_key = ""
        with patch("src.services.evolink.settings", mock_settings):
            assert get_evolink_client() is False


class TestGenerateV2VKling:
    """Tests for Kling O3 video-to-video generation."""

    @pytest.mark.asyncio
    async def test_generate_without_key(self, mock_settings):
        mock_settings.evolink_api_key = ""
        with patch("src.services.evolink.settings", mock_settings):
            result = await generate_v2v_kling("prompt", "https://video.mp4")
            assert isinstance(result, str)
            assert "не настроен" in result

    @pytest.mark.asyncio
    async def test_generate_success(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "id": "task-unified-123",
            "status": "pending",
            "task_info": {"estimated_time": 300},
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "id": "task-unified-123",
            "status": "completed",
            "progress": 100,
            "results": ["https://cdn.evolink.ai/output.mp4"],
        }

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_v2v_kling(
                        prompt="Transform into anime style",
                        video_url="https://source.mp4",
                        quality="720p",
                        keep_audio=True,
                    )

                assert isinstance(result, dict)
                assert result["url"] == "https://cdn.evolink.ai/output.mp4"

    @pytest.mark.asyncio
    async def test_generate_auth_error(self, mock_settings):
        mock_settings.evolink_api_key = "bad-key"

        error_response = MagicMock()
        error_response.status_code = 401
        error_response.json.return_value = {
            "error": {"type": "authentication_error", "message": "Invalid API key"}
        }
        error_response.text = "Unauthorized"

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=error_response)
                mock_cls.return_value = mock_client

                result = await generate_v2v_kling("prompt", "https://video.mp4")
                assert isinstance(result, str)
                assert "EVOLINK_API_KEY" in result

    @pytest.mark.asyncio
    async def test_generate_credits_error(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"

        error_response = MagicMock()
        error_response.status_code = 402
        error_response.json.return_value = {
            "error": {"type": "insufficient_quota_error", "message": "Out of credits"}
        }
        error_response.text = "Payment Required"

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=error_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.set_balance_ok", new_callable=AsyncMock):
                    result = await generate_v2v_kling("prompt", "https://video.mp4")
                    assert isinstance(result, str)
                    assert "Баланс" in result or "исчерпан" in result

    @pytest.mark.asyncio
    async def test_generate_task_failed(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "id": "task-unified-123",
            "status": "pending",
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "id": "task-unified-123",
            "status": "failed",
        }

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_v2v_kling("prompt", "https://video.mp4")
                    assert isinstance(result, str)
                    assert "Ошибка" in result

    @pytest.mark.asyncio
    async def test_prompt_truncation(self, mock_settings):
        """Verify prompt is truncated to 2500 chars."""
        mock_settings.evolink_api_key = "sk-evo-test"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "id": "task-123",
            "status": "pending",
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "status": "completed",
            "results": ["https://result.mp4"],
        }

        long_prompt = "A" * 5000

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_v2v_kling(long_prompt, "https://video.mp4")

                # Check the prompt was truncated in the request
                call_args = mock_client.post.call_args
                payload = call_args.kwargs.get("json", {})
                assert len(payload["prompt"]) == 2500


class TestGenerateI2VKling:
    """Tests for Kling O3 image-to-video generation."""

    @pytest.mark.asyncio
    async def test_generate_without_key(self, mock_settings):
        mock_settings.evolink_api_key = ""
        with patch("src.services.evolink.settings", mock_settings):
            result = await generate_i2v_kling("prompt", "https://image.jpg")
            assert isinstance(result, str)
            assert "не настроен" in result

    @pytest.mark.asyncio
    async def test_generate_success(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "id": "task-i2v-123",
            "status": "pending",
            "task_info": {"estimated_time": 120},
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "id": "task-i2v-123",
            "status": "completed",
            "progress": 100,
            "results": ["https://cdn.evolink.ai/i2v-output.mp4"],
        }

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_i2v_kling(
                        prompt="Animate this photo",
                        image_url="https://image.jpg",
                        duration="5",
                        quality="720p",
                        aspect_ratio="16:9",
                        sound="off",
                    )

                assert isinstance(result, dict)
                assert result["url"] == "https://cdn.evolink.ai/i2v-output.mp4"

    @pytest.mark.asyncio
    async def test_generate_correct_payload(self, mock_settings):
        """Verify payload contains image_urls array, int duration, sound."""
        mock_settings.evolink_api_key = "sk-evo-test"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "id": "task-i2v-456",
            "status": "pending",
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "status": "completed",
            "results": ["https://result.mp4"],
        }

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink.asyncio.sleep", new_callable=AsyncMock):
                    await generate_i2v_kling(
                        "prompt", "https://img.jpg",
                        duration="10", quality="1080p",
                        aspect_ratio="9:16", sound="on",
                    )

                payload = mock_client.post.call_args.kwargs["json"]
                assert payload["model"] == "kling-o3-image-to-video"
                assert payload["image_urls"] == ["https://img.jpg"]
                assert payload["duration"] == 10  # int, not str
                assert payload["quality"] == "1080p"
                assert payload["aspect_ratio"] == "9:16"
                assert payload["sound"] == "on"

    @pytest.mark.asyncio
    async def test_generate_billing_marks_exhausted(self, mock_settings):
        """Verify billing error marks balance exhausted."""
        mock_settings.evolink_api_key = "sk-evo-test"

        error_response = MagicMock()
        error_response.status_code = 402
        error_response.json.return_value = {
            "error": {"type": "insufficient_quota_error", "message": "Out of credits"}
        }
        error_response.text = "Payment Required"

        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=error_response)
                mock_cls.return_value = mock_client

                with patch("src.services.evolink._balance_ok", True):
                    with patch("src.services.evolink.set_balance_ok", new_callable=AsyncMock):
                        result = await generate_i2v_kling("prompt", "https://img.jpg")
                        assert isinstance(result, str)
                        assert "Баланс" in result or "исчерпан" in result


class TestAvailability:
    """Tests for service availability tracking."""

    def test_available_with_key(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"
        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink._balance_ok", True):
                assert is_available() is True

    def test_unavailable_without_key(self, mock_settings):
        mock_settings.evolink_api_key = ""
        with patch("src.services.evolink.settings", mock_settings):
            assert is_available() is False

    def test_unavailable_exhausted_balance(self, mock_settings):
        mock_settings.evolink_api_key = "sk-evo-test"
        with patch("src.services.evolink.settings", mock_settings):
            with patch("src.services.evolink._balance_ok", False):
                assert is_available() is False
