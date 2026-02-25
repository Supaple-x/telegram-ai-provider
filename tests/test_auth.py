"""Tests for src.middleware.auth — AuthMiddleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.middleware.auth import AuthMiddleware


@pytest.fixture
def middleware():
    return AuthMiddleware()


@pytest.fixture
def handler():
    h = AsyncMock(return_value="handler_result")
    return h


def _make_data(user_id: int, username: str | None = None) -> dict:
    user = MagicMock()
    user.id = user_id
    user.username = username
    return {"event_from_user": user}


class TestAuthMiddlewareUnrestricted:
    """When ALLOWED_USERS is empty, everyone gets through."""

    @pytest.mark.asyncio
    async def test_empty_allowed_users_passes(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = []
            result = await middleware(handler, event, _make_data(999))
        assert result == "handler_result"
        handler.assert_awaited_once()


class TestAuthMiddlewareRestricted:
    """When ALLOWED_USERS has entries, only matching users get through."""

    @pytest.mark.asyncio
    async def test_allowed_by_id(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            result = await middleware(handler, event, _make_data(123456))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_allowed_by_username(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["TestUser"]
            mock_s.allowed_users_lower = ["testuser"]
            result = await middleware(handler, event, _make_data(999, "TestUser"))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_username_case_insensitive(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["TestUser"]
            mock_s.allowed_users_lower = ["testuser"]
            result = await middleware(handler, event, _make_data(999, "TESTUSER"))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_denied_user_message(self, middleware, handler):
        from aiogram.types import Message

        event = MagicMock(spec=Message)
        event.answer = AsyncMock()

        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            result = await middleware(handler, event, _make_data(999999, "hacker"))

        assert result is None
        handler.assert_not_awaited()
        event.answer.assert_awaited_once()
        call_args = event.answer.call_args
        assert "авторизованных" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_denied_user_callback(self, middleware, handler):
        from aiogram.types import CallbackQuery

        event = MagicMock(spec=CallbackQuery)
        event.answer = AsyncMock()

        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            result = await middleware(handler, event, _make_data(999999, "hacker"))

        assert result is None
        event.answer.assert_awaited_once()
        call_args = event.answer.call_args
        assert call_args[1].get("show_alert") is True

    @pytest.mark.asyncio
    async def test_no_user_in_data_passes(self, middleware, handler):
        """If no user in data (e.g. system event), let through."""
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            result = await middleware(handler, event, {})
        assert result == "handler_result"
