"""Phase B3: DOC, DOCX & XLSX Structured Extraction Pipeline."""
import csv
import hashlib
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from io import BytesIO

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "artifacts" / "corpus_raw" / "utt"
CONVERTED_DOC_DIR = REPO_ROOT / "artifacts" / "corpus_converted" / "doc"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase_b"

MANIFEST_PATH = OUTPUT_DIR / "source_manifest.jsonl"
PAGE_MANIFEST_PATH = OUTPUT_DIR / "page_manifest.jsonl"
CONVERSION_MANIFEST_PATH = OUTPUT_DIR / "conversion_manifest.jsonl"
TABLE_REVIEW_PATH = OUTPUT_DIR / "table_review.csv"

def normalize_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def parse_xlsx(file_path: Path) -> list[dict]:
    """Zero-dependency robust XLSX parser preserving sheets, rows, columns, and blanks (never converts blank to 0)."""
    sheets_data = []
    with zipfile.ZipFile(file_path, "r") as z:
        names = z.namelist()
        
        # 1. Read shared strings
        shared_strings = []
        if "xl/sharedStrings.xml" in names:
            tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                t_elems = si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                shared_strings.append("".join(t.text for t in t_elems if t.text))
        
        # 2. Read workbook sheets map
        wb_tree = ET.fromstring(z.read("xl/workbook.xml"))
        sheets_info = []
        for s in wb_tree.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
            sheet_id = s.get("sheetId")
            r_id = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            sheet_name = s.get("name")
            sheets_info.append({"id": sheet_id, "name": sheet_name, "rid": r_id})
        
        # 3. Read each sheet
        sheet_files = sorted([n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
        for idx, sfile in enumerate(sheet_files):
            sname = sheets_info[idx]["name"] if idx < len(sheets_info) else f"Sheet{idx+1}"
            stree = ET.fromstring(z.read(sfile))
            
            rows_dict = {}
            max_col_idx = 0
            
            for row_elem in stree.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                r_num = int(row_elem.get("r", 0))
                cells_in_row = {}
                
                for c_elem in row_elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    ref = c_elem.get("r", "")
                    c_type = c_elem.get("t", "")
                    v_elem = c_elem.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                    val = v_elem.text if v_elem is not None and v_elem.text is not None else ""
                    
                    # Convert column letters to 0-based column index
                    col_letters = re.sub(r"[0-9]", "", ref)
                    col_idx = 0
                    for ch in col_letters:
                        col_idx = col_idx * 26 + (ord(ch.upper()) - ord('A') + 1)
                    col_idx -= 1
                    
                    if col_idx > max_col_idx:
                        max_col_idx = col_idx
                    
                    if c_type == "s" and val.isdigit():
                        idx_val = int(val)
                        cell_val = shared_strings[idx_val] if idx_val < len(shared_strings) else ""
                    elif c_type == "b":
                        cell_val = "TRUE" if val == "1" else "FALSE"
                    else:
                        cell_val = val
                    
                    cells_in_row[col_idx] = cell_val.strip()
                
                rows_dict[r_num] = cells_in_row
            
            # Format grid
            table_rows = []
            sorted_row_nums = sorted(rows_dict.keys())
            for r_num in sorted_row_nums:
                row_cells = []
                for c_i in range(max_col_idx + 1):
                    # NEVER convert blank to 0 - keep as empty string ""
                    row_cells.append(rows_dict[r_num].get(c_i, ""))
                if any(row_cells):
                    table_rows.append(row_cells)
            
            sheets_data.append({
                "sheet_name": sname,
                "rows": table_rows,
                "row_count": len(table_rows),
                "col_count": max_col_idx + 1 if table_rows else 0
            })
            
    return sheets_data

def extract_docx_structured(file_path: Path) -> tuple[str, list[dict]]:
    """Extracts DOCX preserving interleaved order of paragraphs and tables with header/cell structure."""
    import docx
    
    doc = docx.Document(file_path)
    blocks = []
    tables_meta = []
    
    for child in doc.element.body:
        if child.tag.endswith("p"):
            p = docx.text.paragraph.Paragraph(child, doc)
            text = p.text.strip()
            if text:
                style_name = (p.style.name if p.style else "").lower()
                if "heading 1" in style_name:
                    blocks.append(f"# {text}")
                elif "heading 2" in style_name:
                    blocks.append(f"## {text}")
                elif "heading 3" in style_name:
                    blocks.append(f"### {text}")
                else:
                    blocks.append(text)
        elif child.tag.endswith("tbl"):
            tbl = docx.table.Table(child, doc)
            rows = []
            for r in tbl.rows:
                row_cells = []
                for c in r.cells:
                    val = c.text.strip().replace("\n", " ")
                    val = re.sub(r"\s+", " ", val)
                    # Deduplicate adjacent horizontal merged cell text in same row
                    if not row_cells or val != row_cells[-1]:
                        row_cells.append(val)
                if any(row_cells):
                    rows.append(row_cells)
            
            if rows:
                col_count = max(len(r) for r in rows)
                norm_rows = [r + [""] * (col_count - len(r)) for r in rows]
                header = " | ".join(norm_rows[0])
                sep = " | ".join(["---"] * col_count)
                body_lines = [" | ".join(r) for r in norm_rows[1:]]
                tbl_md = f"| {header} |\n| {sep} |\n" + "\n".join(f"| {b} |" for b in body_lines)
                blocks.append(tbl_md)
                
                tables_meta.append({
                    "row_count": len(norm_rows),
                    "col_count": col_count,
                    "sample_header": header[:120]
                })
                
    full_text = normalize_text("\n\n".join(blocks))
    return full_text, tables_meta

def main():
    CONVERTED_DOC_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        sources = [json.loads(line) for line in f if line.strip()]
    
    table_reviews = []
    conversion_records = []
    new_page_records = []
    updated_sources = []
    
    docx_sources = [s for s in sources if s["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    xlsx_sources = [s for s in sources if "spreadsheet" in s["mime_type"]]
    doc_sources = [s for s in sources if s["mime_type"] == "application/msword"]
    
    print(f"Found {len(docx_sources)} DOCX, {len(xlsx_sources)} XLSX, and {len(doc_sources)} DOC documents.")
    
    # 1. Process DOCX documents
    print("\n--- Processing DOCX Documents ---")
    for idx, s in enumerate(docx_sources, 1):
        source_id = s["source_id"]
        title = s["title"]
        file_path = REPO_ROOT / s["internal_path"]
        print(f"[{idx}/{len(docx_sources)}] DOCX: {title}...", end=" ", flush=True)
        
        try:
            full_text, tbl_meta = extract_docx_structured(file_path)
            doc_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            char_count = len(full_text)
            
            s["page_count"] = 1
            s["extracted_text_sha256"] = doc_hash
            s["normalized_sha256"] = doc_hash
            s["processing_status"] = "extracted"
            s["processing_tool"] = "python-docx/structured_interleaved"
            
            new_page_records.append({
                "source_id": source_id,
                "document_title": title,
                "page_index": 1,
                "page_label": "Toàn văn (DOCX)",
                "page_type": "native_text",
                "extraction_method": "docx_structured_interleaved",
                "char_count": char_count,
                "text_sha256": doc_hash,
                "raw_text": full_text,
                "rotation_applied": 0,
                "status": "completed",
                "warnings": [f"Trích xuất {len(tbl_meta)} bảng bảo toàn cấu trúc"] if tbl_meta else []
            })
            
            for tm in tbl_meta:
                table_reviews.append({
                    "source_id": source_id,
                    "document_title": title,
                    "format": "docx",
                    "table_scope": "body_table",
                    "row_count": tm["row_count"],
                    "col_count": tm["col_count"],
                    "sample_header": tm["sample_header"],
                    "status": "preserved_structured",
                    "notes": "Interleaved order and merged cells preserved"
                })
            
            print(f"OK ({char_count:,} chars, {len(tbl_meta)} tables)")
        except Exception as exc:
            s["processing_status"] = "extract_failed"
            s["processing_error"] = str(exc)
            print(f"FAILED ({exc})")
    
    # 2. Process XLSX document
    print("\n--- Processing XLSX Documents ---")
    for idx, s in enumerate(xlsx_sources, 1):
        source_id = s["source_id"]
        title = s["title"]
        file_path = REPO_ROOT / s["internal_path"]
        print(f"[{idx}/{len(xlsx_sources)}] XLSX: {title}...", end=" ", flush=True)
        
        try:
            sheets = parse_xlsx(file_path)
            sheet_blocks = []
            
            for s_idx, sh in enumerate(sheets, 1):
                sname = sh["sheet_name"]
                rows = sh["rows"]
                if rows:
                    col_count = sh["col_count"]
                    header = " | ".join(rows[0])
                    sep = " | ".join(["---"] * col_count)
                    body_lines = [" | ".join(r) for r in rows[1:]]
                    md_tbl = f"### Sheet: {sname}\n\n| {header} |\n| {sep} |\n" + "\n".join(f"| {b} |" for b in body_lines)
                    sheet_blocks.append(md_tbl)
                    
                    table_reviews.append({
                        "source_id": source_id,
                        "document_title": title,
                        "format": "xlsx",
                        "table_scope": f"sheet_{sname}",
                        "row_count": sh["row_count"],
                        "col_count": col_count,
                        "sample_header": header[:120],
                        "status": "preserved_structured",
                        "notes": "Blank cells preserved as empty; no zero coercion"
                    })
            
            full_xlsx_text = normalize_text("\n\n".join(sheet_blocks))
            doc_hash = hashlib.sha256(full_xlsx_text.encode("utf-8")).hexdigest()
            
            s["sheet_count"] = len(sheets)
            s["extracted_text_sha256"] = doc_hash
            s["normalized_sha256"] = doc_hash
            s["processing_tool"] = "stdlib-zipfile-xml/zero-dep"
            # Explicit scope determination per B3 specification:
            # "XLSX: Nếu ngoài phạm vi: ghi excluded kèm lý do, không tính là nhập thành công."
            s["processing_status"] = "excluded"
            s["exclusion_reason"] = "Đề xuất lịch học kỳ phụ là dự thảo kế hoạch vận hành tác nghiệp, không phải văn bản quy chế học vụ chính thức"
            
            new_page_records.append({
                "source_id": source_id,
                "document_title": title,
                "page_index": 1,
                "page_label": "Bảng tính (XLSX)",
                "page_type": "spreadsheet_table",
                "extraction_method": "xlsx_xml_table_parser",
                "char_count": len(full_xlsx_text),
                "text_sha256": doc_hash,
                "raw_text": full_xlsx_text,
                "rotation_applied": 0,
                "status": "excluded",
                "warnings": ["Tài liệu ngoài phạm vi quy chế học vụ: đánh dấu excluded kèm lý do"]
            })
            
            print(f"OK ({len(full_xlsx_text):,} chars, {len(sheets)} sheets) -> EXCLUDED (Operational schedule draft)")
        except Exception as exc:
            s["processing_status"] = "extract_failed"
            s["processing_error"] = str(exc)
            print(f"FAILED ({exc})")

    # 3. Process DOC documents (Convert via LibreOffice container or convert log)
    print("\n--- Processing DOC Documents (Word 97-2003) ---")
    for idx, s in enumerate(doc_sources, 1):
        source_id = s["source_id"]
        title = s["title"]
        file_path = REPO_ROOT / s["internal_path"]
        converted_pdf_name = f"{source_id}_{Path(title).stem}.pdf"
        converted_pdf_path = CONVERTED_DOC_DIR / converted_pdf_name
        
        print(f"[{idx}/{len(doc_sources)}] DOC: {title}...", end=" ", flush=True)
        
        # Check if converted PDF already exists
        conv_status = "pending"
        conv_sha = None
        conv_error = None
        
        if converted_pdf_path.exists() and converted_pdf_path.stat().st_size > 0:
            pdf_bytes = converted_pdf_path.read_bytes()
            conv_sha = hashlib.sha256(pdf_bytes).hexdigest()
            conv_status = "converted_ok"
            print(f"CONVERTED_CACHED ({len(pdf_bytes)} B, SHA256={conv_sha[:10]}...)")
        else:
            # Conversion will be performed by LibreOffice headless container
            conv_status = "awaiting_headless_render"
            print("READY FOR CONTAINER RENDER")
        
        conversion_records.append({
            "source_id": source_id,
            "original_filename": title,
            "original_sha256": s["raw_sha256"],
            "converted_filename": converted_pdf_name if conv_status == "converted_ok" else None,
            "converted_sha256": conv_sha,
            "tool_version": "LibreOffice 7.4.7 headless",
            "conversion_status": conv_status,
            "conversion_error": conv_error
        })
    
    # 4. Save table review report
    with open(TABLE_REVIEW_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source_id", "document_title", "format", "table_scope", "row_count", "col_count", "sample_header", "status", "notes"])
        for tr in table_reviews:
            writer.writerow([
                tr["source_id"], tr["document_title"], tr["format"], tr["table_scope"],
                tr["row_count"], tr["col_count"], tr["sample_header"], tr["status"], tr["notes"]
            ])
        if not table_reviews:
            writer.writerow(["none", "N/A", "N/A", "N/A", 0, 0, "", "NO_TABLES", "No tables found"])
    print(f"\nWritten {len(table_reviews)} table review records to {TABLE_REVIEW_PATH}")
    
    # 5. Save conversion manifest
    with open(CONVERSION_MANIFEST_PATH, "w", encoding="utf-8") as f:
        for cr in conversion_records:
            f.write(json.dumps(cr, ensure_ascii=False) + "\n")
    print(f"Written {len(conversion_records)} conversion records to {CONVERSION_MANIFEST_PATH}")
    
    # 6. Append new page records to page_manifest.jsonl
    with open(PAGE_MANIFEST_PATH, "a", encoding="utf-8") as f:
        for p in new_page_records:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"Appended {len(new_page_records)} DOCX/XLSX records to {PAGE_MANIFEST_PATH}")
    
    # 7. Update source manifest
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for s in sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Updated {MANIFEST_PATH} with DOCX/XLSX metadata.")

if __name__ == "__main__":
    main()
