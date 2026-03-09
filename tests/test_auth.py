"""Tests for src.middleware.auth — AuthMiddleware and contact registration."""

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
            with patch("src.middleware.auth.is_approved", return_value=False):
                result = await middleware(handler, event, _make_data(123456))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_allowed_by_username(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["TestUser"]
            mock_s.allowed_users_lower = ["testuser"]
            with patch("src.middleware.auth.is_approved", return_value=False):
                result = await middleware(handler, event, _make_data(999, "TestUser"))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_username_case_insensitive(self, middleware, handler):
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["TestUser"]
            mock_s.allowed_users_lower = ["testuser"]
            with patch("src.middleware.auth.is_approved", return_value=False):
                result = await middleware(handler, event, _make_data(999, "TESTUSER"))
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_allowed_by_db_approval(self, middleware, handler):
        """User approved via contact sharing gets through."""
        event = AsyncMock()
        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            with patch("src.middleware.auth.is_approved", return_value=True):
                result = await middleware(handler, event, _make_data(999999, "newuser"))
        assert result == "handler_result"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_contact_message_passes_through(self, middleware, handler):
        """Contact messages from unauthorized users pass through for registration."""
        from aiogram.types import Message

        event = MagicMock(spec=Message)
        event.contact = MagicMock()  # has a contact

        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            with patch("src.middleware.auth.is_approved", return_value=False):
                result = await middleware(handler, event, _make_data(999999, "newuser"))
        assert result == "handler_result"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_denied_user_message(self, middleware, handler):
        from aiogram.types import Message

        event = MagicMock(spec=Message)
        event.answer = AsyncMock()
        event.contact = None  # no contact

        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            with patch("src.middleware.auth.is_approved", return_value=False):
                result = await middleware(handler, event, _make_data(999999, "hacker"))

        assert result is None
        handler.assert_not_awaited()
        event.answer.assert_awaited_once()
        call_args = event.answer.call_args
        assert "авторизованных" in call_args[0][0]
        # Should show contact keyboard
        assert call_args[1].get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_denied_user_callback(self, middleware, handler):
        from aiogram.types import CallbackQuery

        event = MagicMock(spec=CallbackQuery)
        event.answer = AsyncMock()

        with patch("src.middleware.auth.settings") as mock_s:
            mock_s.allowed_users = ["123456"]
            mock_s.allowed_users_lower = []
            with patch("src.middleware.auth.is_approved", return_value=False):
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


class TestContactHandler:
    """Tests for contact-based self-registration handler."""

    @pytest.mark.asyncio
    async def test_own_contact_approves(self):
        """Sharing own contact grants access."""
        from src.handlers.auth import handle_contact

        message = AsyncMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.from_user.username = "newuser"
        message.contact = MagicMock()
        message.contact.user_id = 12345  # matches from_user.id
        message.contact.phone_number = "+79991234567"

        with patch("src.handlers.auth.is_approved", return_value=False):
            with patch("src.handlers.auth.approve_user", new_callable=AsyncMock) as mock_approve:
                await handle_contact(message)
                mock_approve.assert_called_once_with(12345, "+79991234567", "newuser")

        # Should send success message
        message.answer.assert_awaited_once()
        call_args = message.answer.call_args
        assert "Доступ предоставлен" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_foreign_contact_rejected(self):
        """Sharing someone else's contact is rejected."""
        from src.handlers.auth import handle_contact

        message = AsyncMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.from_user.username = "newuser"
        message.contact = MagicMock()
        message.contact.user_id = 99999  # different user!
        message.contact.phone_number = "+79991234567"

        with patch("src.handlers.auth.is_approved", return_value=False):
            with patch("src.handlers.auth.approve_user", new_callable=AsyncMock) as mock_approve:
                await handle_contact(message)
                mock_approve.assert_not_called()

        message.answer.assert_awaited_once()
        call_args = message.answer.call_args
        assert "свой" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_already_approved_user(self):
        """Already approved user gets confirmation."""
        from src.handlers.auth import handle_contact

        message = AsyncMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.contact = MagicMock()
        message.contact.user_id = 12345

        with patch("src.handlers.auth.is_approved", return_value=True):
            with patch("src.handlers.auth.approve_user", new_callable=AsyncMock) as mock_approve:
                await handle_contact(message)
                mock_approve.assert_not_called()

        message.answer.assert_awaited_once()
        call_args = message.answer.call_args
        assert "уже есть доступ" in call_args[0][0]


class TestAllowedUsersDB:
    """Tests for allowed_users database operations."""

    @pytest.mark.asyncio
    async def test_is_approved_false_by_default(self):
        from src.database.allowed_users import is_approved
        # Unknown user should not be approved
        assert is_approved(999888777) is False

    @pytest.mark.asyncio
    async def test_load_and_check(self):
        from src.database import allowed_users

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[
            {"telegram_id": 111},
            {"telegram_id": 222},
        ])

        with patch("src.database.allowed_users.get_pool", return_value=mock_pool):
            count = await allowed_users.load_approved_users()

        assert count == 2
        assert allowed_users.is_approved(111) is True
        assert allowed_users.is_approved(222) is True
        assert allowed_users.is_approved(333) is False

    @pytest.mark.asyncio
    async def test_approve_user_adds_to_cache(self):
        from src.database import allowed_users

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock()

        with patch("src.database.allowed_users.get_pool", return_value=mock_pool):
            await allowed_users.approve_user(555, "+79990000000", "test")

        assert allowed_users.is_approved(555) is True
        mock_pool.execute.assert_called_once()
