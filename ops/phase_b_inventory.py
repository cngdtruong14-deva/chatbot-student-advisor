"""Phase B1: Inventory Reconciliation, Raw Bytes Preservation & Manifest Generation."""
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIPT_PATH = REPO_ROOT / "vectorstore" / "utt_import_receipt_20260917.json"
RAW_DIR = REPO_ROOT / "artifacts" / "corpus_raw" / "utt"
OUTPUT_DIR = REPO_ROOT / "artifacts" / "phase_b"

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name).strip()

def download_file(source_id: str, dest_path: Path) -> dict:
    url = "https://docs.google.com/uc?export=download"
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # Try direct download first with confirm=t
    try:
        resp = session.get(url, params={"id": source_id, "confirm": "t"}, headers=headers, stream=True, timeout=60)
        # Check if Google Drive returned a download confirmation cookie
        for k, v in resp.cookies.items():
            if k.startswith("download_warning"):
                resp = session.get(url, params={"id": source_id, "confirm": v}, headers=headers, stream=True, timeout=60)
                break
        
        if resp.status_code != 200:
            return {"success": False, "error": f"HTTP_{resp.status_code}"}
        
        hasher = hashlib.sha256()
        total_bytes = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    hasher.update(chunk)
                    total_bytes += len(chunk)
        
        return {
            "success": True,
            "bytes": total_bytes,
            "sha256": hasher.hexdigest(),
            "error": None
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Reading receipt from: {RECEIPT_PATH}")
    with open(RECEIPT_PATH, "r", encoding="utf-8") as f:
        receipt_data = json.load(f)
    
    inventory = receipt_data.get("inventory", [])
    print(f"Total inventory items in baseline: {len(inventory)}")
    
    manifest_records = []
    sha256_to_items = {}
    title_to_items = {}
    
    def process_item(item_info):
        idx, item = item_info
        source_id = item["id"]
        title = item["title"]
        url = item.get("url", f"https://drive.google.com/file/d/{source_id}/view")
        mime = item.get("mime_type", "application/octet-stream")
        reported_size = item.get("size")
        baseline_status = item.get("status", "unknown")
        
        safe_title = sanitize_filename(title)
        filename = f"{source_id}_{safe_title}" if not safe_title.startswith(source_id) else safe_title
        dest_path = RAW_DIR / filename
        
        download_needed = True
        actual_bytes = 0
        raw_sha256 = None
        download_error = None
        download_status = "unknown"
        
        if dest_path.exists() and dest_path.stat().st_size > 0:
            existing_bytes = dest_path.read_bytes()
            if reported_size is None or len(existing_bytes) == reported_size:
                download_needed = False
                actual_bytes = len(existing_bytes)
                raw_sha256 = hashlib.sha256(existing_bytes).hexdigest()
                download_status = "already_cached"
                print(f"[{idx}/{len(inventory)}] CACHED: {title} ({actual_bytes} B, SHA256={raw_sha256[:10]}...)")
        
        if download_needed:
            t0 = time.time()
            res = download_file(source_id, dest_path)
            t1 = time.time()
            if res["success"]:
                actual_bytes = res["bytes"]
                raw_sha256 = res["sha256"]
                download_status = "downloaded_ok"
                print(f"[{idx}/{len(inventory)}] DOWNLOADED: {title} ({actual_bytes} B in {t1-t0:.1f}s, SHA256={raw_sha256[:10]}...)")
            else:
                download_status = "download_failed"
                download_error = res["error"]
                print(f"[{idx}/{len(inventory)}] FAILED: {title} ({download_error})")
        
        now_iso = datetime.now(timezone.utc).isoformat()
        rel_path = str(dest_path.relative_to(REPO_ROOT)).replace("\\", "/")
        
        return {
            "source_id": source_id,
            "url": url,
            "title": title,
            "mime_type": mime,
            "baseline_status": baseline_status,
            "downloaded_at": now_iso,
            "internal_path": rel_path if download_status != "download_failed" else None,
            "size_bytes": actual_bytes,
            "reported_size_bytes": reported_size,
            "raw_sha256": raw_sha256,
            "processing_status": "raw_preserved" if download_status != "download_failed" else "fetch_failed",
            "processing_tool": "python-requests/stream",
            "processing_error": download_error,
            "extracted_text_sha256": None,
            "normalized_sha256": None,
            "page_count": None,
            "sheet_count": None,
            "reviewer": None,
            "review_status": "pending_review",
            "exclusion_reason": None
        }

    from concurrent.futures import ThreadPoolExecutor
    indexed_inventory = list(enumerate(inventory, 1))
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        manifest_records = list(executor.map(process_item, indexed_inventory))
    
    # Sort manifest records by original inventory order
    manifest_records.sort(key=lambda r: next(i for i, item in enumerate(inventory) if item["id"] == r["source_id"]))
    
    for record in manifest_records:
        if record["raw_sha256"]:
            sha256_to_items.setdefault(record["raw_sha256"], []).append(record)
        title_to_items.setdefault(record["title"].strip().lower(), []).append(record)


    # 1. Write source_manifest.jsonl
    manifest_path = OUTPUT_DIR / "source_manifest.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as f:
        for r in manifest_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWritten {len(manifest_records)} entries to {manifest_path}")

    # 2. Write inventory_reconciliation.csv
    reconciliation_path = OUTPUT_DIR / "inventory_reconciliation.csv"
    with open(reconciliation_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_id", "title", "mime_type", "baseline_status",
            "actual_size_bytes", "reported_size_bytes", "size_match",
            "raw_sha256", "reconciliation_status", "notes"
        ])
        for r in manifest_records:
            rep_size = r["reported_size_bytes"]
            act_size = r["size_bytes"]
            size_match = (act_size == rep_size) if rep_size is not None else False
            
            if r["processing_status"] == "fetch_failed":
                recon_status = "missing"
                notes = r["processing_error"] or "Fetch failed"
            elif size_match:
                recon_status = "size_match_hash_not_compared"
                notes = "Size matches baseline; no baseline SHA-256 comparison. Does not establish unchanged bytes or a current Drive listing."
            else:
                recon_status = "changed"
                notes = f"Size mismatch: actual={act_size} vs reported={rep_size}"
            
            writer.writerow([
                r["source_id"],
                r["title"],
                r["mime_type"],
                r["baseline_status"],
                act_size,
                rep_size,
                size_match,
                r["raw_sha256"] or "",
                recon_status,
                notes
            ])
    print(f"Written inventory reconciliation to {reconciliation_path}")

    # 3. Write duplicate_report.csv
    duplicate_path = OUTPUT_DIR / "duplicate_report.csv"
    with open(duplicate_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["duplicate_type", "identifier", "count", "source_ids", "titles", "notes"])
        
        # Check byte-level duplicates
        byte_dups = {k: v for k, v in sha256_to_items.items() if len(v) > 1}
        for sha, items in byte_dups.items():
            writer.writerow([
                "exact_byte_duplicate",
                sha,
                len(items),
                "; ".join(x["source_id"] for x in items),
                "; ".join(x["title"] for x in items),
                "Identical raw binary bytes across multiple entries"
            ])
        
        # Check title duplicates
        title_dups = {k: v for k, v in title_to_items.items() if len(v) > 1}
        for title, items in title_dups.items():
            writer.writerow([
                "title_duplicate",
                title,
                len(items),
                "; ".join(x["source_id"] for x in items),
                "; ".join(x["title"] for x in items),
                "Same filename/title registered multiple times"
            ])
        
        if not byte_dups and not title_dups:
            writer.writerow(["none", "N/A", 0, "", "", "No duplicates detected in current inventory"])
            
    print(f"Written duplicate report to {duplicate_path}")
    
    # Summary
    success_count = sum(1 for r in manifest_records if r["processing_status"] == "raw_preserved")
    failed_count = sum(1 for r in manifest_records if r["processing_status"] == "fetch_failed")
    print(f"\nInventory complete: {success_count}/{len(manifest_records)} files preserved ({failed_count} failed).")

if __name__ == "__main__":
    main()
