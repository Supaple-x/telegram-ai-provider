"""Tests for preferences module — get/set preferred model, caching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database.preferences import (
    DEFAULT_MODEL,
    VALID_MODELS,
    _model_cache,
    get_preferred_model,
    set_preferred_model,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear model cache before each test."""
    _model_cache.clear()
    yield
    _model_cache.clear()


def _mock_pool(conn):
    """Create a mocked asyncpg pool with given connection."""
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    return pool


class TestGetPreferredModel:
    @pytest.mark.asyncio
    async def test_default_when_no_record(self):
        """Returns 'claude' when user has no preference."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            result = await get_preferred_model(111)
        assert result == DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_returns_stored_claude(self):
        """Returns 'claude' from DB."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="claude")

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            result = await get_preferred_model(222)
        assert result == "claude"

    @pytest.mark.asyncio
    async def test_returns_stored_openai(self):
        """Returns 'openai' from DB."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="openai")

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            result = await get_preferred_model(333)
        assert result == "openai"

    @pytest.mark.asyncio
    async def test_invalid_model_returns_default(self):
        """Returns default when DB has an invalid model value."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="invalid_model")

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            result = await get_preferred_model(444)
        assert result == DEFAULT_MODEL

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Second call uses cache, no DB access."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="openai")

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            result1 = await get_preferred_model(555)
            result2 = await get_preferred_model(555)

        assert result1 == result2 == "openai"
        # fetchval should be called only once (first call)
        conn.fetchval.assert_called_once()


class TestSetPreferredModel:
    @pytest.mark.asyncio
    async def test_set_openai(self):
        """Sets model to 'openai' and updates cache."""
        conn = AsyncMock()
        conn.execute = AsyncMock()

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            await set_preferred_model(666, "openai")

        conn.execute.assert_called_once()
        assert _model_cache[666] == "openai"

    @pytest.mark.asyncio
    async def test_set_claude(self):
        """Sets model to 'claude' and updates cache."""
        conn = AsyncMock()
        conn.execute = AsyncMock()

        with patch("src.database.preferences.get_pool", return_value=_mock_pool(conn)):
            await set_preferred_model(777, "claude")

        assert _model_cache[777] == "claude"

    @pytest.mark.asyncio
    async def test_invalid_model_raises(self):
        """Raises ValueError for invalid model."""
        with pytest.raises(ValueError, match="Invalid model"):
            await set_preferred_model(888, "invalid")

    @pytest.mark.asyncio
    async def test_cache_updated_after_set(self):
        """Cache is updated so subsequent get uses new value."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value="claude")
        conn.execute = AsyncMock()
        pool = _mock_pool(conn)

        with patch("src.database.preferences.get_pool", return_value=pool):
            # First: get returns 'claude'
            result1 = await get_preferred_model(999)
            assert result1 == "claude"

            # Set to 'openai'
            await set_preferred_model(999, "openai")

            # Get should return 'openai' from cache (no DB call)
            result2 = await get_preferred_model(999)
            assert result2 == "openai"

        # fetchval called only for the first get (before set)
        conn.fetchval.assert_called_once()


class TestValidModels:
    def test_valid_models_set(self):
        """VALID_MODELS contains expected values."""
        assert VALID_MODELS == {"claude", "openai"}

    def test_default_model(self):
        """DEFAULT_MODEL is 'claude'."""
        assert DEFAULT_MODEL == "claude"
