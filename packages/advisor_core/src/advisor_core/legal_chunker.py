"""Hierarchical legal and regulatory chunker for university academic policies.

Preserves article, clause, table structure, and keeps conditions/exceptions
within the same chunk. Emits provenance ranges and honest locators without
fabricating page numbers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


CONDITION_EXCEPTION_PATTERNS = re.compile(
    r"(\*\s*Lưu ý:|"
    r"Lưu ý:|"
    r"Ngoại lệ:|"
    r"Trừ trường hợp:|"
    r"Trường hợp đặc biệt:|"
    r"Điều kiện để:|"
    r"Trong đó:|"
    r"Quy định chuyển tiếp:)",
    re.IGNORECASE,
)

PAGE_HEADER_PATTERN = re.compile(r"^##\s+Trang\s+(\d+)", re.IGNORECASE)
ARTICLE_PATTERN = re.compile(r"^(Điều\s+\d+[\.:]?\s*([^\n]*))", re.IGNORECASE)
CLAUSE_PATTERN = re.compile(r"^(\d+)\.\s+([^\n]*)")
CHAPTER_PATTERN = re.compile(r"^(Chương\s+[IVXLCDM0-9]+.*|Mục\s+[IVXLCDM0-9]+.*|Phần\s+[IVXLCDM0-9]+.*)", re.IGNORECASE)


class LegalChunk:
    def __init__(
        self,
        *,
        chunk_id: str,
        document_id: str,
        version_id: str,
        text: str,
        text_hash: str,
        scope: str,
        source: str,
        valid_from: str,
        valid_until: str = "9999-12-31",
        page_number: Optional[int] = None,
        locator_type: str = "section",
        locator_label: str = "",
        heading: Optional[str] = None,
        article: Optional[str] = None,
        clause: Optional[str] = None,
        table_id: Optional[str] = None,
        char_start: int = 0,
        char_end: int = 0,
        chunker_version: str = "utt_legal_v1",
        data_origin: str = "user_provided_institutional_document",
        status: str = "reviewed",
        major: Optional[str] = None,
        cohort: Optional[str] = None,
        education_level: Optional[str] = "dai_hoc",
    ):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.version_id = version_id
        self.text = text
        self.text_hash = text_hash
        self.scope = scope
        self.source = source
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.page_number = page_number
        self.locator_type = locator_type
        self.locator_label = locator_label
        self.heading = heading
        self.article = article
        self.clause = clause
        self.table_id = table_id
        self.char_start = char_start
        self.char_end = char_end
        self.chunker_version = chunker_version
        self.data_origin = data_origin
        self.status = status
        self.major = major
        self.cohort = cohort
        self.education_level = education_level

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "text": self.text,
            "text_hash": self.text_hash,
            "scope": self.scope,
            "source": self.source,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "page_number": self.page_number,
            "locator_type": self.locator_type,
            "locator_label": self.locator_label,
            "section": self.locator_label or ("Trang " + str(self.page_number) if self.page_number else "Đoạn"),
            "heading": self.heading,
            "article": self.article,
            "clause": self.clause,
            "table_id": self.table_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "chunker_version": self.chunker_version,
            "data_origin": self.data_origin,
            "status": self.status,
            "major": self.major,
            "cohort": self.cohort,
            "education_level": self.education_level,
        }


def chunk_hierarchical_legal(
    text: str,
    *,
    document_id: str,
    version_id: str,
    scope: str = "utt_corpus",
    source: str = "",
    valid_from: str = "2026-09-19",
    valid_until: str = "9999-12-31",
    major: Optional[str] = None,
    cohort: Optional[str] = None,
    education_level: Optional[str] = "dai_hoc",
    max_chunk_chars: int = 1400,
    chunker_version: str = "utt_legal_v1",
) -> List[Dict[str, Any]]:
    """Chunk legal and academic documents hierarchically preserving clauses and conditions."""
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    chunks: List[Dict[str, Any]] = []

    current_page: Optional[int] = None
    current_chapter: Optional[str] = None
    current_article: Optional[str] = None
    current_clause: Optional[str] = None

    # Track character offsets
    char_offset = 0
    buffer: List[str] = []
    buffer_start = 0
    buffer_locator_type = "section"
    buffer_locator_label = ""
    table_mode = False
    table_lines: List[str] = []

    def flush_buffer():
        nonlocal buffer, buffer_start, buffer_locator_type, buffer_locator_label
        if not buffer:
            return
        chunk_text = "\n".join(buffer).strip()
        if not chunk_text:
            buffer = []
            return

        chunk_end = buffer_start + len(chunk_text)
        digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        chunk_idx = len(chunks)
        cid = hashlib.sha256(f"{document_id}|{version_id}|{chunk_idx}|{digest}".encode("utf-8")).hexdigest()

        # Construct honest locator label
        loc_parts = []
        if current_page is not None:
            loc_parts.append(f"Trang {current_page}")
        if current_article:
            loc_parts.append(current_article)
        if current_clause and current_clause != current_article:
            loc_parts.append(current_clause)
        if not loc_parts:
            loc_parts.append(buffer_locator_label or f"Mục {chunk_idx + 1}")

        final_locator = ", ".join(loc_parts)
        if current_page is None and "Biểu mẫu" not in final_locator:
            final_locator += " (Không có số trang gốc)"

        item = LegalChunk(
            chunk_id=cid,
            document_id=document_id,
            version_id=version_id,
            text=chunk_text,
            text_hash=digest,
            scope=scope,
            source=source,
            valid_from=valid_from,
            valid_until=valid_until,
            page_number=current_page,
            locator_type=buffer_locator_type,
            locator_label=final_locator,
            heading=current_chapter,
            article=current_article,
            clause=current_clause,
            char_start=buffer_start,
            char_end=chunk_end,
            chunker_version=chunker_version,
            major=major,
            cohort=cohort,
            education_level=education_level,
        )
        chunks.append(item.to_dict())
        buffer = []

    # Check if this is an unpaged form (e.g. DOCX with ĐƠN XIN / GIẤY XÁC NHẬN)
    first_few_lines = "\n".join(lines[:10])
    is_form_doc = bool(re.search(r"(\bĐƠN XIN\b|\bGIẤY XÁC NHẬN\b|\bPHIẾU\b|\bBẢNG ĐIỂM\b)", first_few_lines, re.IGNORECASE))
    if is_form_doc and not any(PAGE_HEADER_PATTERN.match(l.strip()) for l in lines):
        buffer_locator_type = "form"
        # Extract title from first non-empty line
        title_line = next((l.strip() for l in lines if l.strip()), "Biểu mẫu")
        buffer_locator_label = f"Biểu mẫu: {title_line}"

    for line in lines:
        line_len = len(line) + 1  # include newline
        s_line = line.strip()

        # Check page header
        page_match = PAGE_HEADER_PATTERN.match(s_line)
        if page_match:
            flush_buffer()
            current_page = int(page_match.group(1))
            char_offset += line_len
            buffer_start = char_offset
            continue

        # Check chapter header
        chap_match = CHAPTER_PATTERN.match(s_line)
        if chap_match:
            flush_buffer()
            current_chapter = s_line
            current_article = None
            current_clause = None
            char_offset += line_len
            buffer_start = char_offset
            buffer.append(s_line)
            buffer_locator_type = "heading"
            continue

        # Check article (Điều)
        art_match = ARTICLE_PATTERN.match(s_line)
        if art_match:
            flush_buffer()
            current_article = art_match.group(1)
            current_clause = None
            char_offset += line_len
            buffer_start = char_offset
            buffer.append(s_line)
            buffer_locator_type = "article"
            continue

        # Check clause (Khoản: e.g. "1. ..." or "2. ...")
        clause_match = CLAUSE_PATTERN.match(s_line)
        if clause_match and current_article:
            # Check if buffer already has substantial content before flushing
            current_len = sum(len(b) for b in buffer)
            if current_len > 350:
                flush_buffer()
                buffer_start = char_offset
                if current_article:
                    # Prepend article header for context preservation
                    buffer.append(f"[{current_article}]")
            current_clause = f"Khoản {clause_match.group(1)}"
            buffer.append(s_line)
            buffer_locator_type = "clause"
            char_offset += line_len
            continue

        # Check markdown table
        if s_line.startswith("|") and s_line.endswith("|"):
            if not table_mode:
                if sum(len(b) for b in buffer) > 200:
                    flush_buffer()
                    buffer_start = char_offset
                table_mode = True
            buffer.append(s_line)
            buffer_locator_type = "table"
            char_offset += line_len
            continue
        else:
            if table_mode:
                if CONDITION_EXCEPTION_PATTERNS.search(s_line) or s_line.startswith("*") or s_line.lower().startswith("ghi chú"):
                    buffer.append(s_line)
                    char_offset += line_len
                    table_mode = False
                    continue
                table_mode = False
                flush_buffer()
                buffer_start = char_offset

        # Check condition/exception: Keep attached to current buffer!
        if CONDITION_EXCEPTION_PATTERNS.search(s_line):
            buffer.append(s_line)
            char_offset += line_len
            continue

        # Normal text line: check size overflow
        if sum(len(b) for b in buffer) + len(s_line) > max_chunk_chars:
            flush_buffer()
            buffer_start = char_offset
            if current_article and not any(current_article in b for b in buffer):
                buffer.append(f"[{current_article}] (tiếp theo)")

        if s_line:
            buffer.append(s_line)
        elif buffer:
            # Empty line can serve as a natural paragraph split if buffer is large enough
            if sum(len(b) for b in buffer) > 600:
                flush_buffer()
                buffer_start = char_offset

        char_offset += line_len

    flush_buffer()
    return chunks
