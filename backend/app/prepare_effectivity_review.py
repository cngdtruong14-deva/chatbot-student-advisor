"""Create an unsigned 44-document effectivity review from a frozen release.

The command copies only immutable identities from the release manifest.  It
never invents effective dates and never marks a review approved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.apply_effectivity_review import HEX64, PROTOCOL, canonical_hash


def _load(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_NOT_OBJECT")
    return value


def prepare(manifest: dict, receipt: dict) -> dict:
    release_id = str(manifest.get("release_id") or "").strip()
    if not release_id or receipt.get("release_id") != release_id:
        raise ValueError("EFFECTIVITY_RELEASE_ID_MISMATCH")
    if manifest.get("source_manifest_hash") != receipt.get("source_manifest_hash"):
        raise ValueError("EFFECTIVITY_SOURCE_MANIFEST_HASH_MISMATCH")
    declared_receipt = str(receipt.get("receipt_sha256") or "")
    if not HEX64.fullmatch(declared_receipt) or canonical_hash(receipt, omit=("receipt_sha256",)) != declared_receipt:
        raise ValueError("EFFECTIVITY_RELEASE_RECEIPT_INVALID")
    sources = manifest.get("source_set")
    if not isinstance(sources, list) or len(sources) != 44 or manifest.get("document_count") != 44:
        raise ValueError("EFFECTIVITY_RELEASE_MUST_CONTAIN_44_DOCUMENTS")
    documents, seen = [], set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("EFFECTIVITY_SOURCE_INVALID")
        source_id = str(source.get("source_id") or "").strip()
        raw_sha256 = str(source.get("raw_sha256") or "")
        if not source_id or source_id in seen or not HEX64.fullmatch(raw_sha256):
            raise ValueError(f"EFFECTIVITY_SOURCE_ID_OR_HASH_INVALID:{source_id}")
        seen.add(source_id)
        documents.append({
            "source_id": source_id,
            "title": str(source.get("title") or source.get("filename") or source_id),
            "raw_sha256": raw_sha256,
            "effective_from": source.get("effective_from") or "OWNER_MUST_SET_YYYY-MM-DD",
            "effective_until": source.get("effective_until"),
            "owner_note": "",
        })
    return {
        "protocol": PROTOCOL,
        "approved": False,
        "owner": "",
        "reviewed_at": "",
        "release_id": release_id,
        "release_receipt_sha256": declared_receipt,
        "documents": documents,
        "approval_sha256": "SET_AFTER_OWNER_REVIEW",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("EFFECTIVITY_TEMPLATE_OUTPUT_EXISTS")
    value = prepare(_load(args.manifest, "MANIFEST"), _load(args.receipt, "RECEIPT"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OWNER_REVIEW_REQUIRED", "document_count": 44, "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
