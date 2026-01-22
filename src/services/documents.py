import io
import logging
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts = []

        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        result = "\n\n".join(text_parts)

        if not result.strip():
            return "⚠️ PDF не содержит извлекаемого текста (возможно, это скан)."

        return result[:15000]  # Limit text length

    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return f"❌ Ошибка чтения PDF: {e}"


async def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX file."""
    try:
        doc = Document(io.BytesIO(file_bytes))
        text_parts = []

        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)

        result = "\n\n".join(text_parts)

        if not result.strip():
            return "⚠️ Документ пуст."

        return result[:15000]  # Limit text length

    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        return f"❌ Ошибка чтения DOCX: {e}"


async def extract_text_from_txt(file_bytes: bytes) -> str:
    """Extract text from TXT file."""
    try:
        # Try different encodings
        for encoding in ["utf-8", "cp1251", "latin-1"]:
            try:
                text = file_bytes.decode(encoding)
                return text[:15000]  # Limit text length
            except UnicodeDecodeError:
                continue

        return "❌ Не удалось определить кодировку файла."

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
        return f"⚠️ Неподдерживаемый формат файла. Поддерживаются: PDF, DOCX, TXT."
