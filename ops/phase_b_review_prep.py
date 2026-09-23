"""Phase B4: OCR Quality Assessment & Critical Content Extraction Dossier Builder."""
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase_b"
PAGE_MANIFEST_PATH = OUTPUT_DIR / "page_manifest.jsonl"
CRITICAL_REVIEW_PATH = OUTPUT_DIR / "critical_content_review.csv"
DOSSIER_HTML_PATH = OUTPUT_DIR / "ocr_review_dossier.html"
QUALITY_REPORT_PATH = OUTPUT_DIR / "ocr_quality_report.json"

CRITICAL_PATTERNS = {
    "gpa_threshold": re.compile(r"(?:gpa|cpa|điểm\s+trung\s+bình|học\s+lực|xuất\s+sắc|loại\s+giỏi|loại\s+khá|cảnh\s+báo\s+học\s+vụ|buộc\s+thôi\s+học|\b[0-4][.,]\d{1,2}\b|\b(?:10|[0-9])[.,]\d{1,2}\b)", re.IGNORECASE),
    "credits": re.compile(r"(?:\d+\s+tín\s+chỉ|\btín\s+chỉ\b|\bhọc\s+phần\b|khối\s+lượng\s+kiến\s+thức)", re.IGNORECASE),
    "decision_date": re.compile(r"(?:quyết\s+định\s+số|số:\s*[\d\w/_-]+|ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|có\s+hiệu\s+lực\s+kể\s+từ)", re.IGNORECASE),
    "condition_exception": re.compile(r"(?:không\s+được|bắt\s+buộc|trừ\s+trường\s+hợp|ngoại\s+lệ|điều\s+kiện\s+được|xét\s+học\s+bổng)", re.IGNORECASE)
}

def calculate_cer_wer(reference: str, hypothesis: str) -> tuple[float, float]:
    """Levenshtein distance based CER and WER calculation."""
    def lev(s1, s2):
        d = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
        for i in range(len(s1) + 1): d[i][0] = i
        for j in range(len(s2) + 1): d[0][j] = j
        for i in range(1, len(s1) + 1):
            for j in range(1, len(s2) + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
        return d[len(s1)][len(s2)]

    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    cer = lev(ref_chars, hyp_chars) / max(len(ref_chars), 1)

    ref_words = reference.split()
    hyp_words = hypothesis.split()
    wer = lev(ref_words, hyp_words) / max(len(ref_words), 1)

    return round(cer * 100, 2), round(wer * 100, 2)

def main():
    if not PAGE_MANIFEST_PATH.exists():
        print(f"Error: {PAGE_MANIFEST_PATH} not found!")
        return

    with open(PAGE_MANIFEST_PATH, "r", encoding="utf-8") as f:
        pages = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(pages)} pages from manifest.")

    critical_pages = []
    stratified_sample = []

    ocr_pages = [p for p in pages if p["extraction_method"] == "ocr_tesseract_vie_eng" and p["char_count"] > 0]
    native_pages = [p for p in pages if p["extraction_method"] in ("pdf_native_text", "docx_structured_interleaved") and p["char_count"] > 0]

    # 1. Identify all pages with critical content
    for p in pages:
        text = p["raw_text"]
        matches = []
        for cat, pattern in CRITICAL_PATTERNS.items():
            found = pattern.findall(text)
            if found:
                matches.append(f"{cat}({len(found)})")
        
        if matches:
            critical_pages.append({
                "page": p,
                "categories": ", ".join(matches),
                "sample_text": text[:300].replace("\n", " ")
            })

    # 2. Stratified sample (at least 30 pages covering diverse documents and methods)
    # 10 from OCR pages, 15 from critical policy pages, 5 from native text / tables
    seen_ids = set()
    sample_pool = []

    for item in critical_pages[:15]:
        p = item["page"]
        if p["text_sha256"] not in seen_ids:
            sample_pool.append({"page": p, "stratum": "critical_policy_rules", "reason": item["categories"]})
            seen_ids.add(p["text_sha256"])

    for p in ocr_pages:
        if len(sample_pool) >= 25: break
        if p["text_sha256"] not in seen_ids:
            sample_pool.append({"page": p, "stratum": "scanned_ocr_evaluation", "reason": "OCR Tesseract accuracy check"})
            seen_ids.add(p["text_sha256"])

    for p in native_pages:
        if len(sample_pool) >= 35: break
        if p["text_sha256"] not in seen_ids:
            sample_pool.append({"page": p, "stratum": "native_structured_text", "reason": "Baseline native text verification"})
            seen_ids.add(p["text_sha256"])

    # 3. Write critical_content_review.csv
    with open(CRITICAL_REVIEW_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_id", "document_title", "page_index", "page_label",
            "extraction_method", "detected_categories", "critical_excerpt",
            "reviewer", "verification_decision", "correction_transcript", "notes"
        ])
        for item in critical_pages:
            p = item["page"]
            writer.writerow([
                p["source_id"],
                p["document_title"],
                p["page_index"],
                p["page_label"],
                p["extraction_method"],
                item["categories"],
                item["sample_text"][:250],
                "Pending Reviewer",
                "pending",
                "",
                ""
            ])
    print(f"Written {len(critical_pages)} critical content items to {CRITICAL_REVIEW_PATH}")

    # 4. Generate HTML Side-by-Side Review Dossier
    html_cards = []
    for idx, item in enumerate(sample_pool, 1):
        p = item["page"]
        text_escaped = p["raw_text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Highlight critical keywords in HTML
        for cat, pat in CRITICAL_PATTERNS.items():
            text_escaped = pat.sub(r'<mark class="crit">\g<0></mark>', text_escaped)

        card = f"""
        <div class="review-card">
            <div class="card-header">
                <h3>#{idx}. {p['document_title']} — {p['page_label']}</h3>
                <span class="badge {p['extraction_method']}">{p['extraction_method']}</span>
                <span class="badge stratum">{item['stratum']}</span>
            </div>
            <div class="card-meta">
                <strong>Source ID:</strong> {p['source_id']} | 
                <strong>Ký tự:</strong> {p['char_count']} | 
                <strong>SHA256:</strong> <code>{p['text_sha256'][:12]}...</code> |
                <strong>Lý do chọn:</strong> {item['reason']}
            </div>
            <div class="card-body">
                <div class="pane extracted">
                    <h4>Văn bản đã trích xuất:</h4>
                    <pre>{text_escaped[:2000]}</pre>
                </div>
                <div class="pane review-form">
                    <h4>Thẩm định của Người duyệt:</h4>
                    <label><input type="checkbox" checked> Nội dung chính xác</label><br>
                    <label><input type="checkbox" checked> Số liệu / Ngưỡng trọng yếu khớp 100%</label><br><br>
                    <label>Ghi chú / Bản đính chính nếu có sai số:</label><br>
                    <textarea rows="4" placeholder="Nhập bản sửa nếu phát hiện lỗi OCR..."></textarea>
                </div>
            </div>
        </div>
        """
        html_cards.append(card)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Hồ sơ Thẩm duyệt Chất lượng OCR & Nội dung Trọng yếu Phase B</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 20px; background: #f8fafc; color: #1e293b; }}
        h1 {{ color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
        .summary-box {{ background: #ffffff; padding: 15px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 25px; }}
        .review-card {{ background: #ffffff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 20px; border: 1px solid #e2e8f0; overflow: hidden; }}
        .card-header {{ background: #f1f5f9; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; }}
        .card-header h3 {{ margin: 0; font-size: 16px; color: #1e293b; }}
        .badge {{ font-size: 12px; padding: 4px 8px; border-radius: 4px; font-weight: 600; text-transform: uppercase; }}
        .badge.ocr_tesseract_vie_eng {{ background: #fef3c7; color: #92400e; }}
        .badge.pdf_native_text {{ background: #dcfce7; color: #166534; }}
        .badge.docx_structured_interleaved {{ background: #e0e7ff; color: #3730a3; }}
        .badge.stratum {{ background: #f3e8ff; color: #6b21a8; }}
        .card-meta {{ padding: 10px 20px; background: #fafafa; font-size: 13px; color: #64748b; border-bottom: 1px solid #f1f5f9; }}
        .card-body {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 20px; }}
        .pane pre {{ background: #f8fafc; padding: 15px; border-radius: 6px; border: 1px solid #e2e8f0; font-size: 13px; white-space: pre-wrap; word-break: break-word; max-height: 350px; overflow-y: auto; line-height: 1.5; }}
        mark.crit {{ background: #fde047; padding: 1px 4px; border-radius: 2px; font-weight: 600; }}
        textarea {{ width: 100%; border: 1px solid #cbd5e1; border-radius: 4px; padding: 8px; font-family: inherit; font-size: 13px; box-sizing: border-box; }}
    </style>
</head>
<body>
    <h1>Hồ sơ Thẩm duyệt Chất lượng OCR & Nội dung Trọng yếu (Phase B)</h1>
    <div class="summary-box">
        <strong>Tổng số trang trong kho:</strong> {len(pages)} trang | 
        <strong>Số trang chứa điều khoản trọng yếu:</strong> {len(critical_pages)} trang | 
        <strong>Mẫu phân tầng đánh giá:</strong> {len(sample_pool)} trang<br>
        <strong>Tiêu chuẩn nghiệm thu:</strong> CER &le; 2.0% cho văn bản thường; số liệu và điều kiện trọng yếu (ngưỡng GPA, tín chỉ, số quyết định) <strong>phải chính xác 100%</strong>.
    </div>
    {''.join(html_cards)}
</body>
</html>
"""
    with open(DOSSIER_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Written HTML review dossier with {len(sample_pool)} pages to {DOSSIER_HTML_PATH}")

    # 5. Write initial ocr_quality_report.json
    quality_summary = {
        "report_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_documents": 74,
        "total_pages_manifested": len(pages),
        "native_text_pages": len(native_pages),
        "ocr_tesseract_pages": len(ocr_pages),
        "pages_with_critical_content": len(critical_pages),
        "stratified_sample_size": len(sample_pool),
        "acceptance_thresholds": {
            "max_cer_percentage": 2.0,
            "critical_numbers_accuracy": "100%",
            "status": "prepared_for_human_review"
        },
        "review_artifacts": {
            "dossier_html": str(DOSSIER_HTML_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
            "critical_content_csv": str(CRITICAL_REVIEW_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
            "failures_csv": "artifacts/phase_b/extraction_failures.csv"
        }
    }
    with open(QUALITY_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(quality_summary, f, ensure_ascii=False, indent=2)
    print(f"Written quality report summary to {QUALITY_REPORT_PATH}")

if __name__ == "__main__":
    main()
