import asyncio
import io
import logging
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)


def _extract_pdf(file_bytes: bytes) -> str:
    """Synchronous PDF text extraction (runs in thread pool)."""
    reader = PdfReader(io.BytesIO(file_bytes))
    text_parts = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)

    result = "\n\n".join(text_parts)

    if not result.strip():
        return "⚠️ PDF не содержит извлекаемого текста (возможно, это скан)."

    return result[:15000]


def _extract_docx(file_bytes: bytes) -> str:
    """Synchronous DOCX text extraction (runs in thread pool)."""
    doc = Document(io.BytesIO(file_bytes))
    text_parts = []

    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)

    result = "\n\n".join(text_parts)

    if not result.strip():
        return "⚠️ Документ пуст."

    return result[:15000]


def _extract_txt(file_bytes: bytes) -> str:
    """Synchronous TXT text extraction with encoding fallback (runs in thread pool)."""
    for encoding in ["utf-8", "cp1251", "latin-1"]:
        try:
            text = file_bytes.decode(encoding)
            return text[:15000]
        except UnicodeDecodeError:
            continue

    return "❌ Не удалось определить кодировку файла."


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file."""
    try:
        return await asyncio.to_thread(_extract_pdf, file_bytes)
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return f"❌ Ошибка чтения PDF: {e}"


async def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX file."""
    try:
        return await asyncio.to_thread(_extract_docx, file_bytes)
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        return f"❌ Ошибка чтения DOCX: {e}"


async def extract_text_from_txt(file_bytes: bytes) -> str:
    """Extract text from TXT file."""
    try:
        return await asyncio.to_thread(_extract_txt, file_bytes)
    except Exception as e:
        logger.error(f"TXT extraction error: {e}")
        return f"❌ Ошибка чтения TXT: {e}"


async def process_document(file_bytes: bytes, filename: str) -> str:
    """Process document and extract text based on file type."""
    filename_lower = filename.lower()

    if filename_lower.endswith(".pdf"):
        return await extract_text_from_pdf(file_bytes)
    elif filename_lower.endswith(".docx"):
        return await extract_text_from_docx(file_bytes)
    elif filename_lower.endswith(".txt"):
        return await extract_text_from_txt(file_bytes)
    else:
        return "⚠️ Неподдерживаемый формат файла. Поддерживаются: PDF, DOCX, TXT."
