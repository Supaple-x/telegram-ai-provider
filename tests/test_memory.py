"""Tests for memory module — build_system_prompt, CRUD logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.claude import build_system_prompt, SYSTEM_PROMPT


class TestBuildSystemPrompt:
    def test_no_memories(self):
        """Without memories, returns base system prompt."""
        result = build_system_prompt(None)
        assert result == SYSTEM_PROMPT

    def test_empty_memories(self):
        """Empty list returns base system prompt."""
        result = build_system_prompt([])
        assert result == SYSTEM_PROMPT

    def test_with_memories(self):
        """Memories are appended in <user_memory> block."""
        memories = ["Меня зовут Алексей", "Я Python-разработчик"]
        result = build_system_prompt(memories)
        assert SYSTEM_PROMPT in result
        assert "<user_memory>" in result
        assert "- Меня зовут Алексей" in result
        assert "- Я Python-разработчик" in result
        assert "</user_memory>" in result

    def test_single_memory(self):
        """Single memory works correctly."""
        result = build_system_prompt(["Предпочитаю краткие ответы"])
        assert "<user_memory>" in result
        assert "- Предпочитаю краткие ответы" in result

    def test_memory_block_order(self):
        """Memory block comes after the base prompt."""
        result = build_system_prompt(["Факт 1"])
        prompt_end = result.index("</user_memory>")
        prompt_start = result.index(SYSTEM_PROMPT[:50])
        assert prompt_start < prompt_end


class TestMemoryCRUD:
    """Test memory database operations with mocked pool."""

    @pytest.mark.asyncio
    async def test_get_memories_empty(self):
        """Returns empty list when no memories exist."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import get_memories
            result = await get_memories(123456)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_memory_texts(self):
        """Returns list of content strings."""
        rows = [{"content": "Факт 1"}, {"content": "Факт 2"}]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import get_memory_texts
            result = await get_memory_texts(123456)
        assert result == ["Факт 1", "Факт 2"]

    @pytest.mark.asyncio
    async def test_add_memory_ok(self):
        """Successfully adds a new memory."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=[None, 5])  # no duplicate, count=5
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import add_memory
            result = await add_memory(123456, "Новый факт")
        assert result == "ok"
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_memory_duplicate(self):
        """Returns 'duplicate' when memory already exists."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=42)  # existing id

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import add_memory
            result = await add_memory(123456, "Существующий факт")
        assert result == "duplicate"

    @pytest.mark.asyncio
    async def test_add_memory_limit(self):
        """Returns 'limit' when max memories reached."""
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=[None, 10])  # no duplicate, count=10

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import add_memory
            result = await add_memory(123456, "Ещё один факт")
        assert result == "limit"

    @pytest.mark.asyncio
    async def test_remove_memory_success(self):
        """Returns True when memory is deleted."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import remove_memory
            result = await remove_memory(123456, 42)
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_memory_not_found(self):
        """Returns False when memory doesn't exist."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import remove_memory
            result = await remove_memory(123456, 999)
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_memories(self):
        """Returns count of deleted memories."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 3")

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("src.database.memory.get_pool", return_value=mock_pool):
            from src.database.memory import clear_memories
            result = await clear_memories(123456)
        assert result == 3
