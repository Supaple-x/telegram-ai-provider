"""Tests for WaveSpeedAI service (Wan 2.2 video-to-video)."""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from src.services.wavespeed import (
    generate_v2v_wan,
    get_wavespeed_client,
    init_wavespeed_client,
    upload_video_to_wavespeed,
)


class TestWavespeedClient:
    """Tests for WaveSpeedAI client initialization."""

    def test_init_with_key(self, mock_settings):
        mock_settings.wavespeed_api_key = "test-key"
        with patch("src.services.wavespeed.settings", mock_settings):
            assert init_wavespeed_client() is True

    def test_init_without_key(self, mock_settings):
        mock_settings.wavespeed_api_key = ""
        with patch("src.services.wavespeed.settings", mock_settings):
            assert init_wavespeed_client() is False

    def test_get_client_with_key(self, mock_settings):
        mock_settings.wavespeed_api_key = "test-key"
        with patch("src.services.wavespeed.settings", mock_settings):
            assert get_wavespeed_client() is True

    def test_get_client_without_key(self, mock_settings):
        mock_settings.wavespeed_api_key = ""
        with patch("src.services.wavespeed.settings", mock_settings):
            assert get_wavespeed_client() is False


class TestUploadVideoToWavespeed:
    """Tests for video upload to WaveSpeedAI."""

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_settings):
        mock_settings.wavespeed_api_key = "test-key"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"download_url": "https://cdn.wavespeed.ai/video.mp4"}
        }

        with patch("src.services.wavespeed.settings", mock_settings):
            with patch("src.services.wavespeed.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                result = await upload_video_to_wavespeed(b"video data", "test.mp4")
                assert result == "https://cdn.wavespeed.ai/video.mp4"

    @pytest.mark.asyncio
    async def test_upload_without_key(self, mock_settings):
        mock_settings.wavespeed_api_key = ""
        with patch("src.services.wavespeed.settings", mock_settings):
            result = await upload_video_to_wavespeed(b"data", "test.mp4")
            assert "не настроен" in result


class TestGenerateV2VWan:
    """Tests for Wan 2.2 video-to-video generation."""

    @pytest.mark.asyncio
    async def test_generate_without_key(self, mock_settings):
        mock_settings.wavespeed_api_key = ""
        with patch("src.services.wavespeed.settings", mock_settings):
            result = await generate_v2v_wan("prompt", "https://video.mp4")
            assert isinstance(result, str)
            assert "не настроен" in result

    @pytest.mark.asyncio
    async def test_generate_success(self, mock_settings):
        mock_settings.wavespeed_api_key = "test-key"

        # Submit response
        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "data": {"id": "task-123", "status": "processing"}
        }

        # Poll response (completed)
        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "data": {
                "status": "completed",
                "outputs": ["https://cdn.wavespeed.ai/result.mp4"],
            }
        }

        with patch("src.services.wavespeed.settings", mock_settings):
            with patch("src.services.wavespeed.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.wavespeed.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_v2v_wan(
                        prompt="anime style",
                        video_url="https://source.mp4",
                        strength=0.6,
                        resolution="720p",
                    )

                assert isinstance(result, dict)
                assert result["url"] == "https://cdn.wavespeed.ai/result.mp4"

    @pytest.mark.asyncio
    async def test_generate_auth_error(self, mock_settings):
        mock_settings.wavespeed_api_key = "bad-key"

        error_response = MagicMock()
        error_response.status_code = 401
        error_response.json.return_value = {"message": "Unauthorized"}
        error_response.text = "Unauthorized"

        with patch("src.services.wavespeed.settings", mock_settings):
            with patch("src.services.wavespeed.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=error_response)
                mock_cls.return_value = mock_client

                result = await generate_v2v_wan("prompt", "https://video.mp4")
                assert isinstance(result, str)
                assert "WAVESPEED_API_KEY" in result

    @pytest.mark.asyncio
    async def test_generate_task_failed(self, mock_settings):
        mock_settings.wavespeed_api_key = "test-key"

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "data": {"id": "task-123", "status": "processing"}
        }

        poll_response = MagicMock()
        poll_response.status_code = 200
        poll_response.json.return_value = {
            "data": {"status": "failed", "error": "GPU out of memory"}
        }

        with patch("src.services.wavespeed.settings", mock_settings):
            with patch("src.services.wavespeed.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(return_value=submit_response)
                mock_client.get = AsyncMock(return_value=poll_response)
                mock_cls.return_value = mock_client

                with patch("src.services.wavespeed.asyncio.sleep", new_callable=AsyncMock):
                    result = await generate_v2v_wan("prompt", "https://video.mp4")
                    assert isinstance(result, str)
                    assert "Ошибка" in result
