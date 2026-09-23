"""Validate/import exactly 1,000 synthetic Academic Demo v2 research cases.

This operator-only job writes research_cases and immutable feature_snapshots
only.  It never creates student profiles, enrollments or predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from advisor_core.ml_boundary import validate_features
from app.store import one, transaction


CONFIRM = "IMPORT_ACADEMIC_DEMO_V2_RESEARCH"


def load_records(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip():
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"RESEARCH_ROW_NOT_OBJECT:{number}")
            result.append(value)
    return result


def validate_release(records: list[dict[str, Any]], schema_path: Path) -> list[tuple[dict[str, Any], str]]:
    if len(records) != 1000:
        raise ValueError(f"RESEARCH_CASE_COUNT_MUST_BE_1000_GOT_{len(records)}")
    seen: set[str] = set()
    validated: list[tuple[dict[str, Any], str]] = []
    for record in records:
        key = str(record.get("case_id") or "").strip()
        if not key or key in seen:
            raise ValueError(f"RESEARCH_CASE_KEY_INVALID_OR_DUPLICATE:{key}")
        seen.add(key)
        if record.get("domain_id") != "academic_demo_v2" or record.get("data_origin") != "synthetic":
            raise ValueError(f"RESEARCH_DOMAIN_ORIGIN_MISMATCH:{key}")
        validate_features(record, schema_path)
        digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        validated.append((record, digest))
    return validated


def import_release(records: list[tuple[dict[str, Any], str]], *, actor_email: str) -> dict[str, int]:
    created_cases = created_snapshots = existing_snapshots = 0
    with transaction() as db:
        actor = one(db, "SELECT id FROM app.users WHERE lower(email)=lower(:email) AND role='admin' AND is_active", email=actor_email)
        if not actor:
            raise ValueError("ACTIVE_ADMIN_ACTOR_REQUIRED")
        for record, digest in records:
            case = one(db, """INSERT INTO app.research_cases(owner_user_id,source_case_key,domain_id,data_origin)
                VALUES(:uid,:key,'academic_demo_v2','synthetic')
                ON CONFLICT(owner_user_id,source_case_key) DO NOTHING RETURNING id""", uid=actor["id"], key=record["case_id"])
            if case:
                created_cases += 1
            else:
                case = one(db, """SELECT id,domain_id,data_origin FROM app.research_cases
                    WHERE owner_user_id=:uid AND source_case_key=:key""", uid=actor["id"], key=record["case_id"])
                if not case or case["domain_id"] != "academic_demo_v2" or case["data_origin"] != "synthetic":
                    raise ValueError(f"RESEARCH_CASE_CONFLICT:{record['case_id']}")
            snapshot = one(db, """INSERT INTO app.feature_snapshots(
                    research_case_id,domain_id,data_origin,feature_schema_id,feature_schema_version,
                    cutoff_day,features_json,source_completeness,snapshot_sha256,created_by)
                VALUES(:case,'academic_demo_v2','synthetic',:schema_id,:schema_version,28,
                    CAST(:features AS jsonb),CAST(:completeness AS jsonb),:sha,:uid)
                ON CONFLICT(snapshot_sha256) DO NOTHING RETURNING id""",
                case=case["id"], schema_id=record["feature_schema_id"], schema_version=record["feature_schema_version"],
                features=json.dumps(record["features"], ensure_ascii=False), completeness=json.dumps(record["source_completeness"]),
                sha=digest, uid=actor["id"])
            if snapshot:
                created_snapshots += 1
            else:
                existing = one(db, "SELECT research_case_id FROM app.feature_snapshots WHERE snapshot_sha256=:sha", sha=digest)
                if not existing or str(existing["research_case_id"]) != str(case["id"]):
                    raise ValueError(f"RESEARCH_SNAPSHOT_HASH_CONFLICT:{record['case_id']}")
                existing_snapshots += 1
    return {"created_cases": created_cases, "created_snapshots": created_snapshots, "existing_snapshots": existing_snapshots}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--schema", default="/contracts/academic_demo_v2_risk_day28.schema.json")
    parser.add_argument("--actor-email", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    validated = validate_release(load_records(Path(args.input)), Path(args.schema))
    if args.dry_run:
        print(json.dumps({"status": "VALIDATED_ONLY", "case_count": len(validated), "student_profiles_changed": False}))
        return 0
    if args.confirm != CONFIRM:
        raise ValueError("EXPLICIT_IMPORT_CONFIRMATION_REQUIRED")
    print(json.dumps({"status": "IMPORTED", **import_release(validated, actor_email=args.actor_email), "student_profiles_changed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
