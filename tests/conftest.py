"""Shared fixtures for all tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    """Create mock settings for tests."""
    s = MagicMock()
    s.telegram_token = "test-token"
    s.anthropic_api_key = "test-key"
    s.openai_api_key = "test-openai-key"
    s.claude_model = "claude-sonnet-4-5-20250929"
    s.openai_model = "gpt-5.2"
    s.max_tokens = 4096
    s.max_context_messages = 20
    s.max_message_length = 4096
    s.allowed_users = ["123456", "TestUser"]
    s.allowed_users_lower = ["testuser"]
    s.rate_limit_messages = 5
    s.rate_limit_window = 60
    s.messages_ttl_days = 30
    s.stream_edit_interval = 1.5
    s.whisper_model = "whisper-1"
    return s


@pytest.fixture
def mock_message():
    """Create a mock Telegram message."""
    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = 123456
    msg.from_user.username = "TestUser"
    msg.chat = MagicMock()
    msg.chat.id = 123456
    msg.text = "Hello"
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.delete = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    return msg


@pytest.fixture
def mock_bot():
    """Create a mock Bot instance."""
    bot = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()
    return bot


@pytest.fixture
def mock_callback():
    """Create a mock CallbackQuery."""
    cb = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = 123456
    cb.from_user.username = "TestUser"
    cb.message = AsyncMock()
    cb.answer = AsyncMock()
    cb.data = "test"
    return cb
