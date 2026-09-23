#!/usr/bin/env python3
"""
Verify Historical Environment & Artifacts Manifest.
Exits with 0 if all hashes match, exits with 1 on any mismatch or missing file.
"""
import hashlib
import json
import sys
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "artifacts" / "audit" / "historical_environment_manifest.json"

    if not manifest_path.exists():
        print(f"[FAIL] Manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    files_to_check = manifest.get("historical_file_hashes", {})
    if not files_to_check:
        print("[FAIL] No files listed in manifest", file=sys.stderr)
        sys.exit(1)

    mismatches = []
    missing = []
    verified_count = 0

    print(f"Verifying {len(files_to_check)} files against {manifest_path.name}...")

    for rel_path, expected in files_to_check.items():
        file_path = repo_root / rel_path
        if not file_path.exists():
            missing.append(rel_path)
            print(f"  MISSING: {rel_path}")
            continue

        h = hashlib.sha256()
        with open(file_path, "rb") as fp:
            while chunk := fp.read(65536):
                h.update(chunk)
        actual_hash = h.hexdigest()
        actual_size = file_path.stat().st_size

        if actual_hash != expected["sha256"]:
            mismatches.append((rel_path, expected["sha256"], actual_hash))
            print(f"  MISMATCH: {rel_path}")
            print(f"    Expected: {expected['sha256']}")
            print(f"    Actual:   {actual_hash}")
        elif actual_size != expected["size_bytes"]:
            mismatches.append((rel_path, f"size {expected['size_bytes']}", f"size {actual_size}"))
            print(f"  SIZE MISMATCH: {rel_path} (exp {expected['size_bytes']}, got {actual_size})")
        else:
            verified_count += 1
            print(f"  OK: {rel_path}")

    print("-" * 60)
    if missing or mismatches:
        print(f"[FAIL] Verification failed! Verified: {verified_count}, Missing: {len(missing)}, Mismatches: {len(mismatches)}", file=sys.stderr)
        sys.exit(1)

    print(f"[PASS] All {verified_count} files strictly verified against manifest. Exit 0.")
    sys.exit(0)

if __name__ == "__main__":
    main()
