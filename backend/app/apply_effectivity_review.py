"""Apply an owner-signed effective-date review to one immutable corpus release.

The review file binds the release receipt and every document version/raw hash.
No dates are inferred.  Without the exact confirmation phrase this command is
read-only and reports what would change.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.store import one, rows, run, transaction


PROTOCOL = "utt_effectivity_review_v1"
CONFIRM = "APPLY_UTT_EFFECTIVITY_REVIEW"
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def canonical_hash(value: Mapping[str, Any], *, omit: tuple[str, ...] = ()) -> str:
    material = {key: item for key, item in value.items() if key not in omit}
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_review(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("protocol") != PROTOCOL or value.get("approved") is not True:
        raise ValueError("EFFECTIVITY_OWNER_APPROVAL_REQUIRED")
    if not str(value.get("owner") or "").strip() or not str(value.get("reviewed_at") or "").strip():
        raise ValueError("EFFECTIVITY_OWNER_AND_DATE_REQUIRED")
    datetime.fromisoformat(str(value["reviewed_at"]).replace("Z", "+00:00"))
    if not HEX64.fullmatch(str(value.get("release_receipt_sha256") or "")):
        raise ValueError("EFFECTIVITY_RECEIPT_HASH_REQUIRED")
    declared = str(value.get("approval_sha256") or "")
    if not HEX64.fullmatch(declared) or canonical_hash(value, omit=("approval_sha256",)) != declared:
        raise ValueError("EFFECTIVITY_APPROVAL_HASH_INVALID")
    documents = value.get("documents")
    if not isinstance(documents, list) or len(documents) != 44:
        raise ValueError("EFFECTIVITY_REVIEW_MUST_COVER_44_DOCUMENTS")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("EFFECTIVITY_DOCUMENT_INVALID")
        source_id = str(item.get("source_id") or "").strip()
        raw_hash = str(item.get("raw_sha256") or "")
        if not source_id or source_id in seen or not HEX64.fullmatch(raw_hash):
            raise ValueError(f"EFFECTIVITY_DOCUMENT_ID_OR_HASH_INVALID:{source_id}")
        seen.add(source_id)
        start = date.fromisoformat(str(item["effective_from"]))
        end = date.fromisoformat(str(item["effective_until"])) if item.get("effective_until") else None
        if end is not None and end < start:
            raise ValueError(f"EFFECTIVITY_DATE_RANGE_INVALID:{source_id}")
        result.append({**item, "source_id": source_id, "raw_sha256": raw_hash, "effective_from": start, "effective_until": end})
    return result


def apply_review(value: Mapping[str, Any], documents: list[dict[str, Any]], *, confirm: str) -> dict[str, Any]:
    with transaction() as db:
        release = one(db, "SELECT id,receipt FROM app.corpus_releases WHERE id=:id FOR UPDATE", id=value.get("release_id"))
        if not release:
            raise ValueError("EFFECTIVITY_RELEASE_NOT_FOUND")
        receipt = release["receipt"] if isinstance(release["receipt"], dict) else json.loads(release["receipt"])
        if receipt.get("receipt_sha256") != value.get("release_receipt_sha256"):
            raise ValueError("EFFECTIVITY_RELEASE_RECEIPT_MISMATCH")
        existing = rows(db, """SELECT id,source_id,raw_sha256,is_effective_date_verified,effective_from,effective_until
            FROM app.document_versions WHERE release_id=:id ORDER BY source_id FOR UPDATE""", id=value["release_id"])
        indexed = {str(row["source_id"]): row for row in existing}
        if len(existing) != 44 or set(indexed) != {item["source_id"] for item in documents}:
            raise ValueError("EFFECTIVITY_RELEASE_DOCUMENT_SET_MISMATCH")
        for item in documents:
            if indexed[item["source_id"]]["raw_sha256"] != item["raw_sha256"]:
                raise ValueError(f"EFFECTIVITY_RAW_HASH_MISMATCH:{item['source_id']}")
        if confirm != CONFIRM:
            return {"status": "VALIDATED_ONLY", "release_id": value["release_id"], "document_count": 44, "updated": 0}
        actor = one(db, "SELECT id FROM app.users WHERE lower(email)=lower(:email) AND role='admin' AND is_active", email=value["owner"])
        if not actor:
            raise ValueError("EFFECTIVITY_ACTIVE_ADMIN_OWNER_REQUIRED")
        for item in documents:
            run(db, """UPDATE app.document_versions SET effective_from=:start,effective_until=:end,
                is_effective_date_verified=true,reviewer=:reviewer WHERE release_id=:release AND source_id=:source""",
                start=item["effective_from"], end=item["effective_until"], reviewer=value["owner"], release=value["release_id"], source=item["source_id"])
        run(db, """INSERT INTO app.audit_logs(actor_id,action,entity_type,entity_id,status,request_id)
            VALUES(:uid,'verify_corpus_effectivity','corpus_release',:release,'verified',:request)""",
            uid=actor["id"], release=value["release_id"], request=value["approval_sha256"])
        return {"status": "APPLIED", "release_id": value["release_id"], "document_count": 44, "updated": 44}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    value = json.loads(Path(args.review).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("EFFECTIVITY_REVIEW_NOT_OBJECT")
    result = apply_review(value, validate_review(value), confirm=args.confirm)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
