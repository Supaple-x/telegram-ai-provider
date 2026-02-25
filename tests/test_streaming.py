"""Tests for streaming — OpenAI stream, Claude stream, stream_to_message."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import anthropic
from src.services.claude import FallbackError

# Mock optional google.genai dependency (not installed locally) before handler imports
for _mod_name in ("google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod_name, MagicMock())
import src.handlers.messages as _msg_mod


# ── helpers ───────────────────────────────────────────────────────────────

async def _collect(async_gen):
    """Collect all items from an async generator into a list."""
    items = []
    async for item in async_gen:
        items.append(item)
    return items


class _MockTextStream:
    """Async iterator that yields predefined text chunks."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class _MockStreamContext:
    """Async context manager mimicking Anthropic's messages.stream()."""

    def __init__(self, chunks: list[str]):
        self.text_stream = _MockTextStream(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockStreamContextError:
    """Async context manager that raises on __aenter__."""

    def __init__(self, error):
        self._error = error

    async def __aenter__(self):
        raise self._error

    async def __aexit__(self, *args):
        pass


# ── OpenAI streaming tests ───────────────────────────────────────────────

class TestOpenaiResponseStream:
    """Tests for generate_openai_response_stream()."""

    @pytest.mark.asyncio
    async def test_yields_error_when_client_none(self):
        from src.services.openai_fallback import generate_openai_response_stream

        with patch("src.services.openai_fallback.client", None):
            chunks = await _collect(
                generate_openai_response_stream([{"role": "user", "content": "Hi"}])
            )

        assert len(chunks) == 1
        assert "не настроена" in chunks[0]

    @pytest.mark.asyncio
    async def test_yields_chunks_on_success(self):
        from src.services.openai_fallback import generate_openai_response_stream

        # Build mock streaming response
        mock_chunks = []
        for text in ["Hello", " world", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            mock_chunks.append(chunk)

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream._items = iter(mock_chunks)
        mock_stream.__anext__ = lambda self: _anext_helper(self)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        with (
            patch("src.services.openai_fallback.client", mock_client),
            patch("src.services.openai_fallback.settings") as mock_s,
        ):
            mock_s.openai_model = "gpt-5.2"
            mock_s.max_tokens = 4096
            chunks = await _collect(
                generate_openai_response_stream([{"role": "user", "content": "Hi"}])
            )

        assert chunks == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_yields_error_on_api_failure(self):
        from src.services.openai_fallback import generate_openai_response_stream

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API timeout")
        )

        with (
            patch("src.services.openai_fallback.client", mock_client),
            patch("src.services.openai_fallback.settings") as mock_s,
        ):
            mock_s.openai_model = "gpt-5.2"
            mock_s.max_tokens = 4096
            chunks = await _collect(
                generate_openai_response_stream([{"role": "user", "content": "Hi"}])
            )

        assert len(chunks) == 1
        assert "Ошибка" in chunks[0]

    @pytest.mark.asyncio
    async def test_skips_empty_delta_chunks(self):
        from src.services.openai_fallback import generate_openai_response_stream

        chunk_with_content = MagicMock()
        chunk_with_content.choices = [MagicMock()]
        chunk_with_content.choices[0].delta.content = "data"

        chunk_empty = MagicMock()
        chunk_empty.choices = [MagicMock()]
        chunk_empty.choices[0].delta.content = None

        chunk_no_choices = MagicMock()
        chunk_no_choices.choices = []

        mock_chunks = [chunk_empty, chunk_with_content, chunk_no_choices]

        mock_stream = AsyncMock()
        mock_stream.__aiter__ = lambda self: self
        mock_stream._items = iter(mock_chunks)
        mock_stream.__anext__ = lambda self: _anext_helper(self)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        with (
            patch("src.services.openai_fallback.client", mock_client),
            patch("src.services.openai_fallback.settings") as mock_s,
        ):
            mock_s.openai_model = "gpt-5.2"
            mock_s.max_tokens = 4096
            chunks = await _collect(
                generate_openai_response_stream([{"role": "user", "content": "Hi"}])
            )

        assert chunks == ["data"]


async def _anext_helper(mock_stream):
    """Helper to iterate mock stream items."""
    try:
        return next(mock_stream._items)
    except StopIteration:
        raise StopAsyncIteration


# ── Claude streaming tests ───────────────────────────────────────────────

class TestClaudeResponseStream:
    """Tests for generate_response_stream()."""

    @pytest.mark.asyncio
    async def test_yields_chunks_on_success(self):
        from src.services.claude import generate_response_stream

        mock_client = MagicMock()
        mock_client.messages.stream.return_value = _MockStreamContext(
            ["Привет", ", как", " дела?"]
        )

        with (
            patch("src.services.claude.client", mock_client),
            patch("src.services.claude.get_client", return_value=mock_client),
            patch("src.services.claude.settings") as mock_s,
        ):
            mock_s.claude_model = "claude-sonnet-4-5-20250929"
            mock_s.max_tokens = 4096
            chunks = await _collect(
                generate_response_stream([{"role": "user", "content": "Hi"}])
            )

        assert chunks == ["Привет", ", как", " дела?"]

    @pytest.mark.asyncio
    async def test_raises_fallback_on_rate_limit(self):
        from src.services.claude import generate_response_stream

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        error = anthropic.RateLimitError(
            message="rate limit",
            response=mock_response,
            body=None,
        )
        mock_client.messages.stream.return_value = _MockStreamContextError(error)

        with (
            patch("src.services.claude.get_client", return_value=mock_client),
            patch("src.services.claude.settings") as mock_s,
        ):
            mock_s.claude_model = "claude-sonnet-4-5-20250929"
            mock_s.max_tokens = 4096
            with pytest.raises(FallbackError, match="лимит"):
                await _collect(
                    generate_response_stream([{"role": "user", "content": "Hi"}])
                )

    @pytest.mark.asyncio
    async def test_raises_fallback_on_overload_529(self):
        from src.services.claude import generate_response_stream

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 529
        mock_response.headers = {}
        error = anthropic.APIStatusError(
            message="overloaded",
            response=mock_response,
            body=None,
        )
        mock_client.messages.stream.return_value = _MockStreamContextError(error)

        with (
            patch("src.services.claude.get_client", return_value=mock_client),
            patch("src.services.claude.settings") as mock_s,
        ):
            mock_s.claude_model = "claude-sonnet-4-5-20250929"
            mock_s.max_tokens = 4096
            with pytest.raises(FallbackError, match="перегружены"):
                await _collect(
                    generate_response_stream([{"role": "user", "content": "Hi"}])
                )

    @pytest.mark.asyncio
    async def test_raises_fallback_on_generic_api_error(self):
        from src.services.claude import generate_response_stream

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}
        error = anthropic.APIError(
            message="internal server error",
            request=MagicMock(),
            body=None,
        )
        mock_client.messages.stream.return_value = _MockStreamContextError(error)

        with (
            patch("src.services.claude.get_client", return_value=mock_client),
            patch("src.services.claude.settings") as mock_s,
        ):
            mock_s.claude_model = "claude-sonnet-4-5-20250929"
            mock_s.max_tokens = 4096
            with pytest.raises(FallbackError, match="Ошибка"):
                await _collect(
                    generate_response_stream([{"role": "user", "content": "Hi"}])
                )


# ── stream_to_message tests ──────────────────────────────────────────────

async def _make_stream(*chunks: str):
    """Create an async generator yielding text chunks."""
    for c in chunks:
        yield c


class TestStreamToMessage:
    """Tests for stream_to_message()."""

    @pytest.mark.asyncio
    async def test_empty_stream_returns_empty(self):
        msg = AsyncMock()
        bot = AsyncMock()

        with patch.object(_msg_mod, "settings") as mock_s:
            mock_s.stream_edit_interval = 1.5

            result = await _msg_mod.stream_to_message(msg, _make_stream(), bot)

        assert result == ""
        msg.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_single_chunk_sends_and_finalizes(self):
        msg = AsyncMock()
        sent_msg = AsyncMock()
        msg.answer.return_value = sent_msg
        bot = AsyncMock()

        with patch.object(_msg_mod, "settings") as mock_s:
            mock_s.stream_edit_interval = 1.5

            result = await _msg_mod.stream_to_message(msg, _make_stream("Hello"), bot)

        assert result == "Hello"
        # First answer should include cursor
        first_call = msg.answer.call_args_list[0]
        assert "▍" in first_call[0][0]
        # Final edit should try Markdown
        sent_msg.edit_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_suffix_appended_on_final_edit(self):
        msg = AsyncMock()
        sent_msg = AsyncMock()
        msg.answer.return_value = sent_msg
        bot = AsyncMock()

        with patch.object(_msg_mod, "settings") as mock_s:
            mock_s.stream_edit_interval = 1.5

            result = await _msg_mod.stream_to_message(
                msg, _make_stream("Response"), bot, suffix="\n\n_GPT-5.2_"
            )

        assert result == "Response"
        # Final edit_text should include suffix
        final_call = sent_msg.edit_text.call_args
        assert "_GPT-5.2_" in final_call[0][0]

    @pytest.mark.asyncio
    async def test_markdown_fallback_on_bad_request(self):
        from aiogram.exceptions import TelegramBadRequest

        msg = AsyncMock()
        sent_msg = AsyncMock()
        # First edit_text (Markdown) fails, second (plain) succeeds
        sent_msg.edit_text.side_effect = [
            TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse"),
            None,  # plain text fallback succeeds
        ]
        msg.answer.return_value = sent_msg
        bot = AsyncMock()

        with patch.object(_msg_mod, "settings") as mock_s:
            mock_s.stream_edit_interval = 1.5

            result = await _msg_mod.stream_to_message(
                msg, _make_stream("**bold**"), bot,
            )

        assert result == "**bold**"
        # Should have been called twice: Markdown then plain
        assert sent_msg.edit_text.await_count == 2

    @pytest.mark.asyncio
    async def test_accumulates_multiple_chunks(self):
        msg = AsyncMock()
        sent_msg = AsyncMock()
        msg.answer.return_value = sent_msg
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "settings") as mock_s,
            patch.object(_msg_mod, "time") as mock_time,
        ):
            mock_s.stream_edit_interval = 1.5
            # Time always 0 → edits only happen on first chunk
            mock_time.monotonic.return_value = 0.0

            result = await _msg_mod.stream_to_message(
                msg, _make_stream("Hello", " ", "world"), bot
            )

        assert result == "Hello world"
