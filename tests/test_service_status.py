"""Tests for service balance status persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database.service_status import (
    get_balance_ok,
    load_all_balance_states,
    set_balance_ok,
)


@pytest.fixture
def mock_pool():
    """Create mock database pool."""
    pool = AsyncMock()
    with patch("src.database.service_status.get_pool", return_value=pool):
        yield pool


class TestGetBalanceOk:
    """Tests for get_balance_ok."""

    @pytest.mark.asyncio
    async def test_returns_true_when_no_record(self, mock_pool):
        mock_pool.fetchval = AsyncMock(return_value=None)
        result = await get_balance_ok("fal")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_when_balance_ok(self, mock_pool):
        mock_pool.fetchval = AsyncMock(return_value=True)
        result = await get_balance_ok("fal")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_exhausted(self, mock_pool):
        mock_pool.fetchval = AsyncMock(return_value=False)
        result = await get_balance_ok("evolink")
        assert result is False


class TestSetBalanceOk:
    """Tests for set_balance_ok."""

    @pytest.mark.asyncio
    async def test_upsert_called(self, mock_pool):
        mock_pool.execute = AsyncMock()
        await set_balance_ok("fal", False)
        mock_pool.execute.assert_called_once()
        args = mock_pool.execute.call_args
        assert "fal" in args[0]
        assert args[0][1] == "fal"
        assert args[0][2] is False


class TestLoadAllBalanceStates:
    """Tests for load_all_balance_states."""

    @pytest.mark.asyncio
    async def test_returns_dict(self, mock_pool):
        mock_pool.fetch = AsyncMock(return_value=[
            {"service_name": "fal", "balance_ok": False},
            {"service_name": "evolink", "balance_ok": True},
        ])
        result = await load_all_balance_states()
        assert result == {"fal": False, "evolink": True}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_records(self, mock_pool):
        mock_pool.fetch = AsyncMock(return_value=[])
        result = await load_all_balance_states()
        assert result == {}


class TestBalancePersistence:
    """Tests for balance persistence integration in services."""

    @pytest.mark.asyncio
    async def test_fal_mark_exhausted_persists(self):
        """Verify fal.ai mark_balance_exhausted schedules DB write."""
        from src.services import video_gen

        original = video_gen._balance_ok
        try:
            with patch("src.services.video_gen.set_balance_ok", new_callable=AsyncMock) as mock_set:
                video_gen._balance_ok = True
                video_gen.mark_balance_exhausted()
                assert video_gen._balance_ok is False
                # Give the fire-and-forget task a chance to run
                import asyncio
                await asyncio.sleep(0)
                mock_set.assert_called_once_with("fal", False)
        finally:
            video_gen._balance_ok = original

    @pytest.mark.asyncio
    async def test_evolink_mark_exhausted_persists(self):
        """Verify EvoLink mark_balance_exhausted schedules DB write."""
        from src.services import evolink

        original = evolink._balance_ok
        try:
            with patch("src.services.evolink.set_balance_ok", new_callable=AsyncMock) as mock_set:
                evolink._balance_ok = True
                evolink.mark_balance_exhausted()
                assert evolink._balance_ok is False
                import asyncio
                await asyncio.sleep(0)
                mock_set.assert_called_once_with("evolink", False)
        finally:
            evolink._balance_ok = original

    @pytest.mark.asyncio
    async def test_wavespeed_mark_exhausted_persists(self):
        """Verify WaveSpeedAI mark_balance_exhausted schedules DB write."""
        from src.services import wavespeed

        original = wavespeed._balance_ok
        try:
            with patch("src.services.wavespeed.set_balance_ok", new_callable=AsyncMock) as mock_set:
                wavespeed._balance_ok = True
                wavespeed.mark_balance_exhausted()
                assert wavespeed._balance_ok is False
                import asyncio
                await asyncio.sleep(0)
                mock_set.assert_called_once_with("wavespeed", False)
        finally:
            wavespeed._balance_ok = original
