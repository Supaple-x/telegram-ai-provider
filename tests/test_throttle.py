"""Tests for src.middleware.throttle — ThrottleMiddleware."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message, CallbackQuery

from src.middleware.throttle import ThrottleMiddleware


@pytest.fixture
def handler():
    return AsyncMock(return_value="ok")


def _make_message_event(user_id: int = 100) -> tuple[MagicMock, dict]:
    event = MagicMock(spec=Message)
    event.answer = AsyncMock()
    user = MagicMock()
    user.id = user_id
    return event, {"event_from_user": user}


class TestThrottleMiddleware:
    @pytest.mark.asyncio
    async def test_allows_within_limit(self, handler):
        mw = ThrottleMiddleware()
        event, data = _make_message_event()

        with patch("src.middleware.throttle.settings") as mock_s:
            mock_s.rate_limit_messages = 3
            mock_s.rate_limit_window = 60

            for _ in range(3):
                result = await mw(handler, event, data)
                assert result == "ok"

        assert handler.await_count == 3

    @pytest.mark.asyncio
    async def test_blocks_over_limit(self, handler):
        mw = ThrottleMiddleware()
        event, data = _make_message_event()

        with patch("src.middleware.throttle.settings") as mock_s:
            mock_s.rate_limit_messages = 2
            mock_s.rate_limit_window = 60

            await mw(handler, event, data)
            await mw(handler, event, data)
            result = await mw(handler, event, data)

        assert result is None
        assert handler.await_count == 2
        event.answer.assert_awaited_once()
        assert "Слишком много" in event.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_different_users_independent(self, handler):
        mw = ThrottleMiddleware()

        with patch("src.middleware.throttle.settings") as mock_s:
            mock_s.rate_limit_messages = 1
            mock_s.rate_limit_window = 60

            event1, data1 = _make_message_event(user_id=1)
            event2, data2 = _make_message_event(user_id=2)

            r1 = await mw(handler, event1, data1)
            r2 = await mw(handler, event2, data2)

        assert r1 == "ok"
        assert r2 == "ok"
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_callback_events_bypass_throttle(self, handler):
        mw = ThrottleMiddleware()
        event = MagicMock(spec=CallbackQuery)
        user = MagicMock()
        user.id = 100
        data = {"event_from_user": user}

        with patch("src.middleware.throttle.settings") as mock_s:
            mock_s.rate_limit_messages = 1
            mock_s.rate_limit_window = 60

            # CallbackQuery should always pass through
            for _ in range(5):
                result = await mw(handler, event, data)
                assert result == "ok"

        assert handler.await_count == 5

    @pytest.mark.asyncio
    async def test_window_expires(self, handler):
        mw = ThrottleMiddleware()
        event, data = _make_message_event()

        with (
            patch("src.middleware.throttle.settings") as mock_s,
            patch("src.middleware.throttle.time") as mock_time,
        ):
            mock_s.rate_limit_messages = 1
            mock_s.rate_limit_window = 60

            # First call at t=1000
            mock_time.monotonic.return_value = 1000.0
            await mw(handler, event, data)

            # Second call at t=1061 — window (60s) expired
            mock_time.monotonic.return_value = 1061.0
            result = await mw(handler, event, data)

        assert result == "ok"
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_window_not_expired_blocks(self, handler):
        """Verify that requests within the window are still blocked."""
        mw = ThrottleMiddleware()
        event, data = _make_message_event()

        with (
            patch("src.middleware.throttle.settings") as mock_s,
            patch("src.middleware.throttle.time") as mock_time,
        ):
            mock_s.rate_limit_messages = 1
            mock_s.rate_limit_window = 60

            # First call at t=1000
            mock_time.monotonic.return_value = 1000.0
            await mw(handler, event, data)

            # Second call at t=1030 — still within 60s window
            mock_time.monotonic.return_value = 1030.0
            result = await mw(handler, event, data)

        assert result is None
        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_no_user_in_data_passes(self, handler):
        mw = ThrottleMiddleware()
        event = MagicMock(spec=Message)

        with patch("src.middleware.throttle.settings") as mock_s:
            mock_s.rate_limit_messages = 1
            mock_s.rate_limit_window = 60

            result = await mw(handler, event, {})

        assert result == "ok"
