"""Tests for src.services — Claude, OpenAI fallback, streaming logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.claude import FallbackError, _build_api_messages


class TestFallbackError:
    def test_is_exception(self):
        err = FallbackError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"


class TestBuildApiMessages:
    def test_simple_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        result = _build_api_messages(messages)
        assert len(result) == 3
        assert result[-1]["content"] == "How are you?"

    def test_with_image_data(self):
        messages = [
            {"role": "user", "content": "What is this?"},
        ]
        image_data = ("base64data", "image/jpeg")
        result = _build_api_messages(messages, image_data=image_data)

        assert len(result) == 1
        content = result[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] == "base64data"
        assert content[1]["type"] == "text"

    def test_preserves_message_order(self):
        messages = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
        ]
        result = _build_api_messages(messages)
        assert [m["content"] for m in result] == ["1", "2", "3"]

    def test_single_message(self):
        messages = [{"role": "user", "content": "Hi"}]
        result = _build_api_messages(messages)
        assert len(result) == 1
        assert result[0]["content"] == "Hi"

    def test_image_default_prompt(self):
        """When content is empty with image, uses default question."""
        messages = [{"role": "user", "content": ""}]
        image_data = ("data", "image/png")
        result = _build_api_messages(messages, image_data=image_data)
        text_block = result[0]["content"][1]
        assert "Что на этом изображении" in text_block["text"]


    def test_context_image_in_middle_message(self):
        """Image data from context (not last message) is included."""
        messages = [
            {"role": "user", "content": "[Изображение] Что это?",
             "image_data": ("img_base64", "image/jpeg")},
            {"role": "assistant", "content": "Это кот."},
            {"role": "user", "content": "Какого цвета?"},
        ]
        result = _build_api_messages(messages)
        assert len(result) == 3
        # First message should have image content
        first = result[0]["content"]
        assert isinstance(first, list)
        assert first[0]["type"] == "image"
        assert first[0]["source"]["data"] == "img_base64"
        # Last message should be plain text
        assert result[2]["content"] == "Какого цвета?"

    def test_context_image_param_overrides_context_for_last(self):
        """Explicit image_data param takes priority over context image for last message."""
        messages = [
            {"role": "user", "content": "Фото",
             "image_data": ("old_img", "image/jpeg")},
        ]
        result = _build_api_messages(messages, image_data=("new_img", "image/png"))
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["source"]["data"] == "new_img"
        assert content[0]["source"]["media_type"] == "image/png"

    def test_multiple_context_images(self):
        """Multiple messages with images are all included."""
        messages = [
            {"role": "user", "content": "Фото 1",
             "image_data": ("img1", "image/jpeg")},
            {"role": "assistant", "content": "Ответ 1"},
            {"role": "user", "content": "Фото 2",
             "image_data": ("img2", "image/png")},
            {"role": "assistant", "content": "Ответ 2"},
            {"role": "user", "content": "Сравни фото"},
        ]
        result = _build_api_messages(messages)
        # Messages 0 and 2 should have images
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["source"]["data"] == "img1"
        assert isinstance(result[2]["content"], list)
        assert result[2]["content"][0]["source"]["data"] == "img2"
        # Others should be plain text
        assert result[1]["content"] == "Ответ 1"
        assert result[4]["content"] == "Сравни фото"

    def test_no_image_data_key_in_context(self):
        """Messages without image_data key are plain text."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = _build_api_messages(messages)
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "Hi"


class TestBuildOpenaiMessages:
    def test_context_image_in_middle(self):
        """Context image is included in OpenAI format."""
        from src.services.openai_fallback import _build_openai_messages
        messages = [
            {"role": "user", "content": "[Изображение] Что это?",
             "image_data": ("img_b64", "image/jpeg")},
            {"role": "assistant", "content": "Это кот."},
            {"role": "user", "content": "Какого цвета?"},
        ]
        result = _build_openai_messages(messages)
        # First is system prompt
        assert result[0]["role"] == "system"
        # Second (user message with image)
        content = result[1]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        assert "img_b64" in content[0]["image_url"]["url"]
        # Last message is plain text
        assert result[3]["content"] == "Какого цвета?"

    def test_system_prompt_passthrough(self):
        """Custom system prompt is used."""
        from src.services.openai_fallback import _build_openai_messages
        messages = [{"role": "user", "content": "Hi"}]
        result = _build_openai_messages(messages, system_prompt="Custom prompt")
        assert result[0]["content"] == "Custom prompt"

    def test_image_param_overrides_context_for_last(self):
        """Explicit image_data overrides context for last message."""
        from src.services.openai_fallback import _build_openai_messages
        messages = [
            {"role": "user", "content": "Фото",
             "image_data": ("old", "image/jpeg")},
        ]
        result = _build_openai_messages(messages, image_data=("new", "image/png"))
        content = result[1]["content"]
        assert isinstance(content, list)
        assert "new" in content[0]["image_url"]["url"]
        assert "image/png" in content[0]["image_url"]["url"]


class TestWebSearch:
    def test_format_search_results_empty(self):
        from src.services.web_search import format_search_results
        result = format_search_results([])
        assert "не найдены" in result

    def test_format_search_results(self):
        from src.services.web_search import SearchResult, format_search_results
        results = [
            SearchResult(title="Title 1", url="https://example.com", snippet="Snippet 1"),
            SearchResult(title="Title 2", url="https://test.com", snippet="Snippet 2"),
        ]
        formatted = format_search_results(results)
        assert "Title 1" in formatted
        assert "https://example.com" in formatted
        assert "Snippet 2" in formatted
        assert "1." in formatted
        assert "2." in formatted

    @pytest.mark.asyncio
    async def test_search_web_handles_error(self):
        from src.services.web_search import search_web
        with patch("src.services.web_search._sync_search", side_effect=Exception("API error")):
            results = await search_web("test query")
        assert results == []


class TestTranscription:
    @pytest.mark.asyncio
    async def test_transcribe_no_client(self):
        from src.services.transcription import transcribe_audio
        with patch("src.services.transcription.client", None):
            result = await transcribe_audio(b"audio data")
        assert "не настроена" in result

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self):
        from src.services.transcription import transcribe_audio

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "   "
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with patch("src.services.transcription.client", mock_client):
            result = await transcribe_audio(b"audio data")
        assert "Не удалось распознать" in result

    @pytest.mark.asyncio
    async def test_transcribe_success(self):
        from src.services.transcription import transcribe_audio

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "Привет, как дела?"
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with patch("src.services.transcription.client", mock_client):
            with patch("src.services.transcription.settings") as mock_s:
                mock_s.whisper_model = "whisper-1"
                result = await transcribe_audio(b"audio data")
        assert result == "Привет, как дела?"

    @pytest.mark.asyncio
    async def test_transcribe_api_error(self):
        from src.services.transcription import transcribe_audio

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("API timeout")
        )

        with patch("src.services.transcription.client", mock_client):
            with patch("src.services.transcription.settings") as mock_s:
                mock_s.whisper_model = "whisper-1"
                result = await transcribe_audio(b"audio data")
        assert "Ошибка" in result
