"""Bounded text extraction for administrator-reviewed PDF and DOCX uploads."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path, PurePosixPath

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EXPANDED_DOCX_BYTES = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 2_000
MAX_PDF_PAGES = 200
MAX_TEXT_CHARS = 100_000

ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}


class DocumentExtractionError(ValueError):
    pass


def validate_upload_metadata(filename: str | None, content_type: str | None) -> None:
    if not filename or Path(filename).name != filename:
        raise DocumentExtractionError("INVALID_FILENAME")
    extension = Path(filename).suffix.lower()
    allowed = ALLOWED_CONTENT_TYPES.get(extension)
    if not allowed:
        raise DocumentExtractionError("UNSUPPORTED_DOCUMENT_TYPE")
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in allowed:
        raise DocumentExtractionError("DOCUMENT_CONTENT_TYPE_MISMATCH")


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise DocumentExtractionError("DOCUMENT_TEXT_NOT_FOUND")
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentExtractionError("DOCUMENT_TEXT_TOO_LARGE")
    return text


MAX_OCR_PAGES = 20
MAX_IMAGE_PIXELS = 10_000_000
OCR_PAGE_TIMEOUT_SECONDS = 10


def _ocr_image(image_bytes: bytes | None) -> str:
    if not image_bytes:
        return ""
    try:
        import pytesseract
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        img = Image.open(io.BytesIO(image_bytes))
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise DocumentExtractionError("IMAGE_DIMENSION_LIMIT_EXCEEDED")
        text = pytesseract.image_to_string(img, lang="vie+eng", timeout=OCR_PAGE_TIMEOUT_SECONDS)
        return text.strip()
    except DocumentExtractionError:
        raise
    except Exception:
        return ""


def _render_pdf_page_to_image(payload: bytes, page_num: int) -> bytes | None:
    try:
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(payload, first_page=page_num, last_page=page_num,
                                    dpi=150, size=2500, thread_count=1, timeout=OCR_PAGE_TIMEOUT_SECONDS)
        if images:
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pass
    return None


def _pdf(payload: bytes) -> tuple[str, int, list[str]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if reader.is_encrypted:
            raise DocumentExtractionError("ENCRYPTED_PDF_NOT_SUPPORTED")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentExtractionError("PDF_PAGE_LIMIT_EXCEEDED")
        pages = []
        ocr_count = 0
        for number, page in enumerate(reader.pages, 1):
            page_text = (page.extract_text() or "").strip()
            if len(page_text) >= 30:
                pages.append(f"## Trang {number}\n\n{page_text}")
            else:
                # Scanned or image-only page: trigger OCR
                if ocr_count >= MAX_OCR_PAGES:
                    raise DocumentExtractionError("OCR_PAGE_LIMIT_EXCEEDED")
                ocr_count += 1
                img_bytes = _render_pdf_page_to_image(payload, number)
                ocr_text = _ocr_image(img_bytes)
                final_page_text = ocr_text or page_text
                if final_page_text:
                    pages.append(f"## Trang {number}\n\n{final_page_text}")
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("INVALID_PDF") from exc
    warnings = [f"Đã áp dụng OCR cho {ocr_count} trang scan."] if ocr_count else []
    return _normalize("\n\n".join(pages)), len(reader.pages), warnings


def _image(payload: bytes) -> tuple[str, int, list[str]]:
    if not (payload.startswith(b"\x89PNG") or payload.startswith(b"\xff\xd8\xff")):
        raise DocumentExtractionError("INVALID_IMAGE")
    ocr_text = _ocr_image(payload)
    if not ocr_text:
        raise DocumentExtractionError("DOCUMENT_TEXT_NOT_FOUND")
    return _normalize(f"## Hình ảnh văn bản trích xuất\n\n{ocr_text}"), 1, ["Văn bản được nhận diện qua OCR từ ảnh chụp."]


def _safe_docx(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise DocumentExtractionError("DOCX_ENTRY_LIMIT_EXCEEDED")
            if sum(item.file_size for item in entries) > MAX_EXPANDED_DOCX_BYTES:
                raise DocumentExtractionError("DOCX_EXPANDED_SIZE_LIMIT_EXCEEDED")
            for item in entries:
                path = PurePosixPath(item.filename)
                unix_mode = item.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or (unix_mode & 0o170000) == 0o120000:
                    raise DocumentExtractionError("UNSAFE_DOCX_PATH")
            if "[Content_Types].xml" not in {item.filename for item in entries}:
                raise DocumentExtractionError("INVALID_DOCX")
    except DocumentExtractionError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentExtractionError("INVALID_DOCX") from exc


def _docx(payload: bytes) -> tuple[str, int, list[str]]:
    from docx import Document

    _safe_docx(payload)
    try:
        document = Document(io.BytesIO(payload))
        blocks = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    blocks.append(" | ".join(cells))
    except Exception as exc:
        raise DocumentExtractionError("INVALID_DOCX") from exc
    return _normalize("\n\n".join(blocks)), 0, []


def extract_document(filename: str | None, payload: bytes, content_type: str | None = None) -> dict:
    if not filename or Path(filename).name != filename:
        raise DocumentExtractionError("INVALID_FILENAME")
    if content_type is not None:
        validate_upload_metadata(filename, content_type)
    if not payload:
        raise DocumentExtractionError("EMPTY_DOCUMENT")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError("DOCUMENT_FILE_TOO_LARGE")
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        text, page_count, warnings = _pdf(payload)
        kind = "pdf"
    elif extension == ".docx":
        text, page_count, warnings = _docx(payload)
        kind = "docx"
    elif extension in {".png", ".jpg", ".jpeg"}:
        text, page_count, warnings = _image(payload)
        kind = "image"
    else:
        raise DocumentExtractionError("UNSUPPORTED_DOCUMENT_TYPE")
    return {
        "filename": filename,
        "format": kind,
        "content": text,
        "character_count": len(text),
        "page_count": page_count or None,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "warnings": warnings,
    }
