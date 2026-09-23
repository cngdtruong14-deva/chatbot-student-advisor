"""Sign dates already reviewed by the owner; this command never fills dates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.apply_effectivity_review import canonical_hash, validate_review


CONFIRM = "OWNER_APPROVED_44_EFFECTIVITY_DATES"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", required=True, help="Active admin email used by apply_effectivity_review")
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != CONFIRM:
        raise ValueError("EFFECTIVITY_EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    if args.output.exists():
        raise ValueError("EFFECTIVITY_SIGNED_OUTPUT_EXISTS")
    value = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or len(value.get("documents", [])) != 44:
        raise ValueError("EFFECTIVITY_REVIEW_MUST_COVER_44_DOCUMENTS")
    for item in value["documents"]:
        if item.get("effective_from") in (None, "", "OWNER_MUST_SET_YYYY-MM-DD"):
            raise ValueError(f"EFFECTIVITY_DATE_NOT_REVIEWED:{item.get('source_id')}")
    value.update(approved=True, owner=args.owner.strip(), reviewed_at=datetime.now(timezone.utc).isoformat())
    value.pop("approval_sha256", None)
    value["approval_sha256"] = canonical_hash(value)
    validate_review(value)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "OWNER_SIGNED", "document_count": 44, "approval_sha256": value["approval_sha256"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
