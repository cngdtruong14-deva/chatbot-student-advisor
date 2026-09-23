"""Extract text from the 13 converted DOC PDFs and append to page_manifest.jsonl."""
import hashlib
import json
import re
from pathlib import Path
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parent.parent
CONVERTED_DOC_DIR = REPO_ROOT / "artifacts" / "corpus_converted" / "doc"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase_b"
MANIFEST_PATH = OUTPUT_DIR / "source_manifest.jsonl"
PAGE_MANIFEST_PATH = OUTPUT_DIR / "page_manifest.jsonl"

def normalize_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def main():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        sources = [json.loads(line) for line in f if line.strip()]
    
    doc_sources = [s for s in sources if s["mime_type"] == "application/msword"]
    print(f"Processing {len(doc_sources)} converted DOC documents...")
    
    new_pages = []
    doc_hash_map = {}
    
    for s in doc_sources:
        sid = s["source_id"]
        title = s["title"]
        pdf_name = f"{sid}_{Path(title).stem}.pdf"
        pdf_path = CONVERTED_DOC_DIR / pdf_name
        
        if not pdf_path.exists():
            print(f"ERROR: {pdf_path} not found!")
            continue
        
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        doc_texts = []
        
        for p_num, page in enumerate(reader.pages, 1):
            text = normalize_text(page.extract_text() or "")
            doc_texts.append(text)
            p_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            new_pages.append({
                "source_id": sid,
                "document_title": title,
                "page_index": p_num,
                "page_label": f"Trang {p_num} (converted from DOC)",
                "page_type": "native_text",
                "extraction_method": "libreoffice_pdf_native_text",
                "char_count": len(text),
                "text_sha256": p_hash,
                "raw_text": text,
                "rotation_applied": 0,
                "status": "completed",
                "warnings": ["Chuyển đổi từ định dạng Word 97-2003 qua LibreOffice headless"]
            })
        
        full_doc_text = "\n\n".join(doc_texts)
        doc_hash = hashlib.sha256(full_doc_text.encode("utf-8")).hexdigest()
        doc_hash_map[sid] = {
            "page_count": total_pages,
            "text_sha256": doc_hash,
            "char_count": len(full_doc_text)
        }
        print(f"  -> {title}: {total_pages} pages, {len(full_doc_text)} chars, SHA256={doc_hash[:10]}")
    
    with open(PAGE_MANIFEST_PATH, "a", encoding="utf-8") as f:
        for p in new_pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"Appended {len(new_pages)} page records to {PAGE_MANIFEST_PATH}")
    
    # Update source manifest
    updated = []
    for s in sources:
        sid = s["source_id"]
        if sid in doc_hash_map:
            s["page_count"] = doc_hash_map[sid]["page_count"]
            s["extracted_text_sha256"] = doc_hash_map[sid]["text_sha256"]
            s["normalized_sha256"] = doc_hash_map[sid]["text_sha256"]
            s["processing_status"] = "extracted"
            s["processing_tool"] = "libreoffice_7.4.7+pypdf"
        updated.append(s)
        
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for s in updated:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Updated {MANIFEST_PATH} with converted DOC metadata.")

if __name__ == "__main__":
    main()
