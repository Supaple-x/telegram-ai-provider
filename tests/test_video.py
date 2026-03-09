"""Tests for video generation service and handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.video_gen import (
    generate_video,
    generate_video_from_image,
    get_video_client,
    init_video_client,
    upload_image_to_fal,
    upload_video_to_fal,
)


class TestVideoClient:
    """Tests for video client initialization."""

    def test_init_video_client_with_key(self, mock_settings):
        """Test client initialization with API key."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = init_video_client()
            assert result is True

    def test_init_video_client_without_key(self, mock_settings):
        """Test client initialization without API key."""
        mock_settings.fal_api_key = ""
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = init_video_client()
            assert result is False

    def test_get_video_client_with_key(self, mock_settings):
        """Test get_video_client returns True when configured."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = get_video_client()
            assert result is True

    def test_get_video_client_without_key(self, mock_settings):
        """Test get_video_client returns False when not configured."""
        mock_settings.fal_api_key = ""
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = get_video_client()
            assert result is False


class TestUploadImageToFal:
    """Tests for image upload to fal.storage."""

    @pytest.mark.asyncio
    async def test_upload_success(self, mock_settings):
        """Test successful image upload."""
        mock_settings.fal_api_key = "test-key"
        image_bytes = b"fake image data"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = "https://fal.storage/image.jpg"
                
                result = await upload_image_to_fal(image_bytes, "image.jpg")
                
                assert result == "https://fal.storage/image.jpg"
                mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_without_key(self, mock_settings):
        """Test upload fails without API key."""
        mock_settings.fal_api_key = ""
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = await upload_image_to_fal(b"data", "image.jpg")
            
            assert result == "fal.ai не настроен (отсутствует FAL_KEY)"

    @pytest.mark.asyncio
    async def test_upload_auth_error(self, mock_settings):
        """Test upload with authentication error."""
        mock_settings.fal_api_key = "invalid-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.side_effect = Exception("authentication failed")
                
                result = await upload_image_to_fal(b"data", "image.jpg")
                
                assert "Неверный FAL_KEY" in result


class TestGenerateVideo:
    """Tests for text-to-video generation."""

    @pytest.mark.asyncio
    async def test_generate_success(self, mock_settings):
        """Test successful video generation."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = {
                    "video": {"url": "https://video.mp4"},
                    "seed": 42
                }
                
                result = await generate_video(
                    prompt="A dog running",
                    duration="5",
                    resolution="720p",
                    aspect_ratio="16:9",
                    generate_audio=True,
                )
                
                assert isinstance(result, dict)
                assert result["url"] == "https://video.mp4"
                assert result["seed"] == 42

    @pytest.mark.asyncio
    async def test_generate_without_key(self, mock_settings):
        """Test generation fails without API key."""
        mock_settings.fal_api_key = ""
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = await generate_video("prompt")
            
            assert isinstance(result, str)
            assert "не настроена" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_rate_limit_retry(self, mock_settings):
        """Test retry on rate limit error."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                # First two calls raise Exception with rate limit message, third succeeds
                mock_to_thread.side_effect = [
                    Exception("rate limit exceeded"),
                    Exception("rate limit exceeded"),
                    {"video": {"url": "https://video.mp4"}, "seed": 42}
                ]
                
                result = await generate_video("prompt")
                
                assert isinstance(result, dict)
                assert result["url"] == "https://video.mp4"
                assert mock_to_thread.call_count == 3

    @pytest.mark.asyncio
    async def test_generate_rate_limit_exhausted(self, mock_settings):
        """Test failure after max retries on rate limit."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.side_effect = Exception("rate limit exceeded")
                
                result = await generate_video("prompt")
                
                assert isinstance(result, str)
                assert "Превышен лимит" in result or "rate limit" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_auth_error(self, mock_settings):
        """Test generation with authentication error."""
        mock_settings.fal_api_key = "invalid-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.side_effect = Exception("authentication failed")
                
                result = await generate_video("prompt")
                
                assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_generate_empty_response(self, mock_settings):
        """Test generation with empty response."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = {}
                
                result = await generate_video("prompt")
                
                assert isinstance(result, str)
                assert "Не удалось получить видео" in result


class TestGenerateVideoFromImage:
    """Tests for image-to-video generation."""

    @pytest.mark.asyncio
    async def test_generate_from_image_success(self, mock_settings):
        """Test successful image-to-video generation."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = {
                    "video": {"url": "https://video.mp4"},
                    "seed": 123
                }
                
                result = await generate_video_from_image(
                    prompt="Animate this",
                    image_url="https://image.jpg",
                    duration="5",
                    resolution="720p",
                    aspect_ratio="16:9",
                    generate_audio=True,
                )
                
                assert isinstance(result, dict)
                assert result["url"] == "https://video.mp4"

    @pytest.mark.asyncio
    async def test_generate_from_image_without_key(self, mock_settings):
        """Test image-to-video fails without API key."""
        mock_settings.fal_api_key = ""
        
        with patch("src.services.video_gen.settings", mock_settings):
            result = await generate_video_from_image("prompt", "https://image.jpg")
            
            assert isinstance(result, str)
            assert "не настроена" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_from_image_default_params(self, mock_settings):
        """Test image-to-video with default parameters."""
        mock_settings.fal_api_key = "test-key"
        
        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = {"video": {"url": "https://video.mp4"}}
                
                await generate_video_from_image("prompt", "https://image.jpg")
                
                # Check arguments passed correctly
                call_args = mock_to_thread.call_args
                # First positional arg is the function (subscribe), kwargs contain arguments
                assert call_args[1]["arguments"]["prompt"] == "prompt"
                assert call_args[1]["arguments"]["image_url"] == "https://image.jpg"
                assert call_args[1]["arguments"]["duration"] == "5"
                assert call_args[1]["arguments"]["resolution"] == "720p"


class TestUploadVideoToFal:
    """Tests for video upload to fal.storage."""

    @pytest.mark.asyncio
    async def test_upload_video_success(self, mock_settings):
        mock_settings.fal_api_key = "test-key"

        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                mock_to_thread.return_value = "https://fal.storage/video.mp4"

                result = await upload_video_to_fal(b"fake video data", "video.mp4")

                assert result == "https://fal.storage/video.mp4"
                mock_to_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_video_without_key(self, mock_settings):
        mock_settings.fal_api_key = ""

        with patch("src.services.video_gen.settings", mock_settings):
            result = await upload_video_to_fal(b"data", "video.mp4")
            assert "не настроен" in result

    @pytest.mark.asyncio
    async def test_upload_video_billing_error(self, mock_settings):
        mock_settings.fal_api_key = "test-key"

        with patch("src.services.video_gen.settings", mock_settings):
            with patch("src.services.video_gen.asyncio.to_thread") as mock_to_thread:
                with patch("src.services.video_gen.set_balance_ok", new_callable=AsyncMock):
                    mock_to_thread.side_effect = Exception("User is locked. Reason: Exhausted balance")

                    result = await upload_video_to_fal(b"data", "video.mp4")
                    assert "Баланс" in result or "исчерпан" in result
