"""Tests for src.services.documents — document extraction."""

import io

import pytest

from src.services.documents import (
    extract_text_from_txt,
    process_document,
)


class TestExtractTextFromTxt:
    @pytest.mark.asyncio
    async def test_utf8_text(self):
        text = "Hello, world! Привет, мир!"
        result = await extract_text_from_txt(text.encode("utf-8"))
        assert result == text

    @pytest.mark.asyncio
    async def test_cp1251_text(self):
        text = "Привет, мир!"
        result = await extract_text_from_txt(text.encode("cp1251"))
        assert "Привет" in result

    @pytest.mark.asyncio
    async def test_empty_file(self):
        result = await extract_text_from_txt(b"")
        assert result == ""

    @pytest.mark.asyncio
    async def test_truncates_long_text(self):
        text = "x" * 20000
        result = await extract_text_from_txt(text.encode("utf-8"))
        assert len(result) == 15000


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_txt_file(self):
        result = await process_document(b"Hello", "test.txt")
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_txt_case_insensitive(self):
        result = await process_document(b"Hello", "TEST.TXT")
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_unsupported_format(self):
        result = await process_document(b"data", "test.xyz")
        assert "Неподдерживаемый формат" in result

    @pytest.mark.asyncio
    async def test_pdf_invalid_data(self):
        result = await process_document(b"not a pdf", "test.pdf")
        assert "❌" in result

    @pytest.mark.asyncio
    async def test_docx_invalid_data(self):
        result = await process_document(b"not a docx", "test.docx")
        assert "❌" in result
