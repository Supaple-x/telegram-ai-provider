"""Tests for handler logic — handle_ai_response, send_fallback_offer, handle_text."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.claude import FallbackError

# Mock optional google.genai dependency (not installed locally) before handler imports
for _mod_name in ("google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod_name, MagicMock())
import src.handlers.messages as _msg_mod


# ── helpers ───────────────────────────────────────────────────────────────

async def _make_stream(*chunks: str):
    """Create an async generator yielding text chunks."""
    for c in chunks:
        yield c


# ── handle_ai_response tests ─────────────────────────────────────────────

class TestHandleAiResponse:
    """Tests for handle_ai_response() — routing, fallback, DB save."""

    @pytest.mark.asyncio
    async def test_claude_happy_path_saves_response(self):
        msg = AsyncMock()
        sent_msg = AsyncMock()
        msg.answer.return_value = sent_msg
        bot = AsyncMock()

        context = [{"role": "user", "content": "Hi"}]

        with (
            patch.object(_msg_mod, "generate_response_stream"),
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock) as mock_add,
        ):
            mock_stm.return_value = "AI response text"

            await _msg_mod.handle_ai_response(
                msg, bot, 123, context, "system prompt", "claude",
            )

        mock_add.assert_awaited_once_with(123, "assistant", "AI response text")

    @pytest.mark.asyncio
    async def test_openai_happy_path_saves_response(self):
        msg = AsyncMock()
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "generate_openai_response_stream"),
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock) as mock_add,
        ):
            mock_stm.return_value = "GPT response"

            await _msg_mod.handle_ai_response(
                msg, bot, 123, [{"role": "user", "content": "Hi"}],
                "system prompt", "openai",
            )

        mock_add.assert_awaited_once_with(123, "assistant", "GPT response")

    @pytest.mark.asyncio
    async def test_openai_adds_suffix(self):
        msg = AsyncMock()
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "generate_openai_response_stream"),
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock),
        ):
            mock_stm.return_value = "response"

            await _msg_mod.handle_ai_response(
                msg, bot, 123, [{"role": "user", "content": "Hi"}],
                "system prompt", "openai",
            )

        # Verify suffix was passed to stream_to_message
        call_kwargs = mock_stm.call_args
        suffix = call_kwargs.kwargs.get("suffix", "")
        assert "GPT-5.2" in suffix

    @pytest.mark.asyncio
    async def test_claude_fallback_error_offers_gpt(self):
        msg = AsyncMock()
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "generate_response_stream"),
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "send_fallback_offer", new_callable=AsyncMock) as mock_offer,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock) as mock_add,
        ):
            mock_stm.side_effect = FallbackError("⚠️ Rate limit")

            await _msg_mod.handle_ai_response(
                msg, bot, 123, [{"role": "user", "content": "Hi"}],
                "system prompt", "claude",
            )

        mock_offer.assert_awaited_once()
        assert "Rate limit" in mock_offer.call_args[0][1]
        # Response should NOT be saved to DB
        mock_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_response_not_saved(self):
        msg = AsyncMock()
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "generate_response_stream"),
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock) as mock_add,
        ):
            mock_stm.return_value = ""

            await _msg_mod.handle_ai_response(
                msg, bot, 123, [{"role": "user", "content": "Hi"}],
                "system prompt", "claude",
            )

        mock_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_image_data_to_stream(self):
        msg = AsyncMock()
        bot = AsyncMock()
        image = ("base64data", "image/jpeg")

        with (
            patch.object(_msg_mod, "generate_response_stream") as mock_gen,
            patch.object(_msg_mod, "stream_to_message", new_callable=AsyncMock) as mock_stm,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock),
        ):
            mock_stm.return_value = "response"

            await _msg_mod.handle_ai_response(
                msg, bot, 123, [{"role": "user", "content": "Hi"}],
                "system prompt", "claude", image_data=image,
            )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args
        assert call_kwargs.kwargs["image_data"] == image


# ── send_fallback_offer tests ────────────────────────────────────────────

class TestSendFallbackOffer:
    """Tests for send_fallback_offer()."""

    @pytest.mark.asyncio
    async def test_with_openai_client_shows_button(self):
        msg = AsyncMock()

        with patch.object(_msg_mod, "get_openai_client", return_value=MagicMock()):
            await _msg_mod.send_fallback_offer(msg, "⚠️ Claude unavailable")

        msg.answer.assert_awaited_once()
        call_args = msg.answer.call_args
        assert "GPT-5.2" in call_args[0][0]
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_without_openai_client_shows_error(self):
        msg = AsyncMock()

        with patch.object(_msg_mod, "get_openai_client", return_value=None):
            await _msg_mod.send_fallback_offer(msg, "⚠️ Claude unavailable")

        msg.answer.assert_awaited_once()
        call_args = msg.answer.call_args
        assert "Попробуйте позже" in call_args[0][0]
        assert call_args[1].get("reply_markup") is None


# ── handle_text tests ────────────────────────────────────────────────────

class TestHandleText:
    """Tests for handle_text() — main message handler."""

    @pytest.mark.asyncio
    async def test_happy_path(self):
        msg = AsyncMock()
        msg.from_user.id = 123
        msg.from_user.username = "testuser"
        msg.text = "Hello AI"
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "ensure_user", new_callable=AsyncMock),
            patch.object(_msg_mod, "get_context", new_callable=AsyncMock) as mock_ctx,
            patch.object(_msg_mod, "get_memory_texts", new_callable=AsyncMock) as mock_mem,
            patch.object(_msg_mod, "get_preferred_model", new_callable=AsyncMock) as mock_pref,
            patch.object(_msg_mod, "add_message", new_callable=AsyncMock) as mock_add,
            patch.object(_msg_mod, "build_system_prompt") as mock_build,
            patch.object(_msg_mod, "handle_ai_response", new_callable=AsyncMock) as mock_handle,
        ):
            mock_ctx.return_value = []
            mock_mem.return_value = ["fact1"]
            mock_pref.return_value = "claude"
            mock_build.return_value = "system prompt with memory"

            await _msg_mod.handle_text(msg, bot)

        # User message saved
        mock_add.assert_awaited_once_with(123, "user", "Hello AI")
        # AI response called with correct params
        mock_handle.assert_awaited_once()
        args = mock_handle.call_args
        assert args[0][2] == 123  # user_id
        assert args[0][5] == "claude"  # preferred model

    @pytest.mark.asyncio
    async def test_db_error_shows_message(self):
        import asyncpg

        msg = AsyncMock()
        msg.from_user.id = 123
        msg.from_user.username = "testuser"
        msg.text = "Hello"
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "ensure_user", new_callable=AsyncMock),
            patch.object(
                _msg_mod, "get_context",
                new_callable=AsyncMock,
                side_effect=asyncpg.PostgresError("connection lost"),
            ),
        ):
            await _msg_mod.handle_text(msg, bot)

        msg.answer.assert_awaited()
        error_text = msg.answer.call_args[0][0]
        assert "Ошибка базы данных" in error_text

    @pytest.mark.asyncio
    async def test_unexpected_error_shows_generic_message(self):
        msg = AsyncMock()
        msg.from_user.id = 123
        msg.from_user.username = "testuser"
        msg.text = "Hello"
        bot = AsyncMock()

        with (
            patch.object(_msg_mod, "ensure_user", new_callable=AsyncMock),
            patch.object(
                _msg_mod, "get_context",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            await _msg_mod.handle_text(msg, bot)

        msg.answer.assert_awaited()
        error_text = msg.answer.call_args[0][0]
        assert "Произошла ошибка" in error_text
