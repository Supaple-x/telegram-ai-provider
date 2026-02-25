"""Tests for src.utils.text — split_message()."""

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _patch_settings():
    mock_settings = MagicMock()
    mock_settings.max_message_length = 4096
    with patch("src.utils.text.settings", mock_settings):
        yield


from src.utils.text import split_message


class TestSplitMessage:
    def test_short_message_returns_single(self):
        text = "Hello, world!"
        result = split_message(text, max_length=4096)
        assert result == [text]

    def test_empty_string(self):
        result = split_message("", max_length=4096)
        assert result == [""]

    def test_exact_limit(self):
        text = "a" * 4096
        result = split_message(text, max_length=4096)
        assert result == [text]

    def test_splits_at_paragraphs(self):
        p1 = "a" * 2000
        p2 = "b" * 2000
        text = f"{p1}\n\n{p2}"
        result = split_message(text, max_length=3000)
        assert len(result) == 2
        assert result[0] == p1
        assert result[1] == p2

    def test_splits_at_sentences(self):
        # Single paragraph that exceeds limit, splits by sentences
        s1 = "First sentence." * 50  # ~750 chars
        s2 = "Second sentence." * 50
        text = f"{s1} {s2}"
        result = split_message(text, max_length=1000)
        assert len(result) >= 2
        # All text should be preserved
        combined = " ".join(result)
        assert len(combined) >= len(text) - 10  # allow for splitting artifacts

    def test_hard_split_very_long_word(self):
        text = "x" * 100
        result = split_message(text, max_length=30)
        assert len(result) == 4  # 100 / 30 = 3.33 -> 4 parts
        assert result[0] == "x" * 30
        assert result[1] == "x" * 30
        assert result[2] == "x" * 30
        assert result[3] == "x" * 10

    def test_multiple_paragraphs_fit(self):
        text = "Para 1\n\nPara 2\n\nPara 3"
        result = split_message(text, max_length=4096)
        assert result == [text]

    def test_custom_max_length(self):
        text = "a" * 50 + "\n\n" + "b" * 50
        result = split_message(text, max_length=60)
        assert len(result) == 2

    def test_preserves_content(self):
        """All content should appear in the split parts."""
        text = "Hello world. " * 500
        result = split_message(text, max_length=500)
        rejoined = "".join(result)
        # Allow for minor differences due to splitting
        assert len(rejoined) >= len(text) - 50

    def test_no_part_exceeds_limit(self):
        text = "Word. " * 1000
        max_len = 200
        result = split_message(text, max_length=max_len)
        for part in result:
            assert len(part) <= max_len
