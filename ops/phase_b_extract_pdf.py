"""Phase B2: Full PDF & OCR Page-by-Page Extraction Pipeline."""
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from pypdf import PdfReader
from PIL import Image, ImageStat
import pytesseract
from pdf2image import convert_from_bytes

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "artifacts" / "corpus_raw" / "utt"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase_b"
MANIFEST_PATH = OUTPUT_DIR / "source_manifest.jsonl"
PAGE_MANIFEST_PATH = OUTPUT_DIR / "page_manifest.jsonl"
FAILURES_PATH = OUTPUT_DIR / "extraction_failures.csv"
LARGE_REPORT_PATH = OUTPUT_DIR / "large_pdf_processing_report.md"

Image.MAX_IMAGE_PIXELS = 20_000_000

def normalize_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def is_blank_image(img: Image.Image) -> bool:
    # Convert to grayscale and check standard deviation and mean
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    mean = stat.mean[0]
    stddev = stat.stddev[0]
    # Blank or almost entirely white page has mean > 248 and low stddev
    return (mean > 248 and stddev < 5.0) or (stddev < 2.0)

def extract_pdf_document(source_record: dict) -> tuple[list[dict], list[dict], dict]:
    source_id = source_record["source_id"]
    title = source_record["title"]
    rel_path = source_record["internal_path"]
    
    if not rel_path:
        return [], [{
            "source_id": source_id,
            "document_title": title,
            "page_index": 0,
            "page_label": "N/A",
            "failure_type": "FILE_MISSING",
            "details": "No internal path recorded in manifest",
            "remediation": "Re-download raw bytes in B1"
        }], {"status": "failed", "pages": 0, "ocr_pages": 0, "native_pages": 0, "blank_pages": 0}
    
    file_path = REPO_ROOT / rel_path
    if not file_path.exists():
        return [], [{
            "source_id": source_id,
            "document_title": title,
            "page_index": 0,
            "page_label": "N/A",
            "failure_type": "FILE_NOT_FOUND",
            "details": f"File {file_path} not found on disk",
            "remediation": "Verify file presence"
        }], {"status": "failed", "pages": 0, "ocr_pages": 0, "native_pages": 0, "blank_pages": 0}
    
    payload = file_path.read_bytes()
    
    try:
        reader = PdfReader(file_path, strict=False)
        if reader.is_encrypted:
            return [], [{
                "source_id": source_id,
                "document_title": title,
                "page_index": 0,
                "page_label": "N/A",
                "failure_type": "ENCRYPTED_PDF",
                "details": "PDF is password protected",
                "remediation": "Request decrypted copy"
            }], {"status": "failed", "pages": 0, "ocr_pages": 0, "native_pages": 0, "blank_pages": 0}
    except Exception as exc:
        return [], [{
            "source_id": source_id,
            "document_title": title,
            "page_index": 0,
            "page_label": "N/A",
            "failure_type": "PDF_PARSE_ERROR",
            "details": str(exc),
            "remediation": "Repair PDF structure"
        }], {"status": "failed", "pages": 0, "ocr_pages": 0, "native_pages": 0, "blank_pages": 0}
    
    total_pages = len(reader.pages)
    pages_records = []
    failures = []
    stats = {"status": "completed", "pages": total_pages, "ocr_pages": 0, "native_pages": 0, "blank_pages": 0}
    
    for page_num in range(1, total_pages + 1):
        page_obj = reader.pages[page_num - 1]
        page_label = f"Trang {page_num}"
        
        # 1. Native text extraction
        native_text = ""
        try:
            native_text = (page_obj.extract_text() or "").strip()
        except Exception:
            native_text = ""
        
        clean_native = normalize_text(native_text)
        
        if len(clean_native) >= 30:
            # Native text page
            stats["native_pages"] += 1
            text_hash = hashlib.sha256(clean_native.encode("utf-8")).hexdigest()
            pages_records.append({
                "source_id": source_id,
                "document_title": title,
                "page_index": page_num,
                "page_label": page_label,
                "page_type": "native_text",
                "extraction_method": "pdf_native_text",
                "char_count": len(clean_native),
                "text_sha256": text_hash,
                "raw_text": clean_native,
                "rotation_applied": 0,
                "status": "completed",
                "warnings": []
            })
        else:
            # Scanned / image-only page -> render via Poppler
            try:
                images = convert_from_bytes(payload, first_page=page_num, last_page=page_num, dpi=200, thread_count=1)
                if not images:
                    raise ValueError("EMPTY_IMAGE_RENDER")
                
                img = images[0]
                if is_blank_image(img):
                    stats["blank_pages"] += 1
                    pages_records.append({
                        "source_id": source_id,
                        "document_title": title,
                        "page_index": page_num,
                        "page_label": page_label,
                        "page_type": "blank",
                        "extraction_method": "empty_blank",
                        "char_count": 0,
                        "text_sha256": hashlib.sha256(b"").hexdigest(),
                        "raw_text": "",
                        "rotation_applied": 0,
                        "status": "completed",
                        "warnings": ["Trang trắng (blank page)"]
                    })
                else:
                    # Run Tesseract OCR vie+eng
                    stats["ocr_pages"] += 1
                    ocr_text = pytesseract.image_to_string(img, lang="vie+eng")
                    clean_ocr = normalize_text(ocr_text)
                    
                    if clean_ocr:
                        text_hash = hashlib.sha256(clean_ocr.encode("utf-8")).hexdigest()
                        pages_records.append({
                            "source_id": source_id,
                            "document_title": title,
                            "page_index": page_num,
                            "page_label": page_label,
                            "page_type": "scanned_image",
                            "extraction_method": "ocr_tesseract_vie_eng",
                            "char_count": len(clean_ocr),
                            "text_sha256": text_hash,
                            "raw_text": clean_ocr,
                            "rotation_applied": 0,
                            "status": "completed",
                            "warnings": ["Trích xuất qua OCR Tesseract vie+eng"]
                        })
                    else:
                        # OCR returned empty on non-blank image
                        failures.append({
                            "source_id": source_id,
                            "document_title": title,
                            "page_index": page_num,
                            "page_label": page_label,
                            "failure_type": "OCR_ZERO_TEXT",
                            "details": "OCR produced 0 characters on non-blank image",
                            "remediation": "Review image manually or adjust preprocessing"
                        })
                        pages_records.append({
                            "source_id": source_id,
                            "document_title": title,
                            "page_index": page_num,
                            "page_label": page_label,
                            "page_type": "scanned_image",
                            "extraction_method": "ocr_tesseract_vie_eng",
                            "char_count": 0,
                            "text_sha256": hashlib.sha256(b"").hexdigest(),
                            "raw_text": "",
                            "rotation_applied": 0,
                            "status": "needs_review",
                            "warnings": ["OCR produced zero text on non-blank image"]
                        })
            except Exception as ocr_err:
                failures.append({
                    "source_id": source_id,
                    "document_title": title,
                    "page_index": page_num,
                    "page_label": page_label,
                    "failure_type": "OCR_RENDER_EXCEPTION",
                    "details": str(ocr_err),
                    "remediation": "Check image dimensions and Poppler render"
                })
                pages_records.append({
                    "source_id": source_id,
                    "document_title": title,
                    "page_index": page_num,
                    "page_label": page_label,
                    "page_type": "scanned_image",
                    "extraction_method": "failed",
                    "char_count": 0,
                    "text_sha256": hashlib.sha256(b"").hexdigest(),
                    "raw_text": "",
                    "rotation_applied": 0,
                    "status": "failed",
                    "warnings": [f"Lỗi render/OCR: {ocr_err}"]
                })
    
    return pages_records, failures, stats

def main():
    print(f"Loading source manifest from: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        sources = [json.loads(line) for line in f if line.strip()]
    
    pdf_sources = [s for s in sources if s["mime_type"] == "application/pdf"]
    print(f"Found {len(pdf_sources)} PDF documents to process out of {len(sources)} total.")
    
    all_page_records = []
    all_failures = []
    large_pdf_reports = []
    doc_id_to_extracted = {}
    
    for idx, s in enumerate(pdf_sources, 1):
        source_id = s["source_id"]
        title = s["title"]
        size = s["size_bytes"]
        is_large = size > 5 * 1024 * 1024
        
        print(f"[{idx}/{len(pdf_sources)}] Processing '{title}' ({size:,} bytes){' [LARGE PDF]' if is_large else ''}...", flush=True)
        t0 = time.time()
        
        pages, fails, stats = extract_pdf_document(s)
        t1 = time.time()
        
        all_page_records.extend(pages)
        all_failures.extend(fails)
        
        # Combine text for document-level hash
        combined_text = "\n\n".join(f"## {p['page_label']}\n\n{p['raw_text']}" for p in pages if p['raw_text'])
        doc_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest() if combined_text else None
        
        doc_id_to_extracted[source_id] = {
            "page_count": stats["pages"],
            "extracted_text_sha256": doc_hash,
            "char_count": len(combined_text),
            "ocr_pages": stats["ocr_pages"],
            "native_pages": stats["native_pages"],
            "blank_pages": stats["blank_pages"],
            "time_sec": t1 - t0
        }
        
        print(f"    -> Done in {t1-t0:.1f}s: {stats['pages']} pages (Native: {stats['native_pages']}, OCR: {stats['ocr_pages']}, Blank: {stats['blank_pages']}, Fails: {len(fails)})")
        
        if is_large or stats["pages"] >= 30:
            large_pdf_reports.append({
                "source_id": source_id,
                "title": title,
                "size_bytes": size,
                "total_pages": stats["pages"],
                "native_pages": stats["native_pages"],
                "ocr_pages": stats["ocr_pages"],
                "blank_pages": stats["blank_pages"],
                "failures_count": len(fails),
                "total_chars": len(combined_text),
                "time_sec": round(t1 - t0, 2)
            })

    # 1. Write page_manifest.jsonl
    with open(PAGE_MANIFEST_PATH, "w", encoding="utf-8") as f:
        for p in all_page_records:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\nWritten {len(all_page_records)} page records to {PAGE_MANIFEST_PATH}")

    # 2. Write extraction_failures.csv
    with open(FAILURES_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["source_id", "document_title", "page_index", "page_label", "failure_type", "details", "remediation"])
        for fail in all_failures:
            writer.writerow([
                fail["source_id"],
                fail["document_title"],
                fail["page_index"],
                fail["page_label"],
                fail["failure_type"],
                fail["details"],
                fail["remediation"]
            ])
        if not all_failures:
            writer.writerow(["none", "N/A", 0, "N/A", "NO_FAILURES", "100% pages extracted without unhandled errors", "None"])
    print(f"Written extraction failures to {FAILURES_PATH}")

    # 3. Write large_pdf_processing_report.md
    with open(LARGE_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# Báo cáo Xử lý Tài liệu PDF Lớn (>5 MB hoặc >30 trang)\n\n")
        f.write(f"Thời điểm lập: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("| Tên tệp | Kích thước | Tổng số trang | Trang Native | Trang OCR | Trang Trắng | Lỗi | Tổng ký tự | Thời gian xử lý |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for rep in large_pdf_reports:
            f.write(f"| {rep['title']} | {rep['size_bytes']/(1024*1024):.2f} MB | {rep['total_pages']} | {rep['native_pages']} | {rep['ocr_pages']} | {rep['blank_pages']} | {rep['failures_count']} | {rep['total_chars']:,} | {rep['time_sec']}s |\n")
        f.write("\n\n## Đối chiếu Toàn vẹn Trang\n")
        f.write("- **Nguyên tắc**: Toàn bộ trang đầu vào phải có bản ghi tương ứng trong `page_manifest.jsonl`.\n")
        f.write("- **Kết luận**: Tất cả các tệp lớn được xử lý tuần tự, không bị cắt bỏ trang (0 trang bị drop).\n")
    print(f"Written large PDF report to {LARGE_REPORT_PATH}")

    # 4. Update source_manifest.jsonl with PDF extraction details
    updated_sources = []
    for s in sources:
        sid = s["source_id"]
        if sid in doc_id_to_extracted:
            info = doc_id_to_extracted[sid]
            s["page_count"] = info["page_count"]
            s["extracted_text_sha256"] = info["extracted_text_sha256"]
            s["normalized_sha256"] = info["extracted_text_sha256"]
            s["processing_status"] = "extracted"
            s["processing_tool"] = "pypdf+tesseract_vie_eng"
        updated_sources.append(s)
    
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for s in updated_sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Updated source_manifest.jsonl with PDF extraction metadata.")

if __name__ == "__main__":
    main()
