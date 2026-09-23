"""Run explicit research-only inference for Academic Demo v2 snapshots.

The job is idempotent per (snapshot, active model), requires an active approved
artifact, and never reads or writes student-profile tables.
"""
from __future__ import annotations

import argparse
import json

from app import ai_runtime
from app.store import one, rows, transaction


CONFIRM = "PREDICT_ACADEMIC_DEMO_V2_RESEARCH"


def preflight() -> tuple[dict, list[dict]]:
    approved = ai_runtime.approved_bundle("academic_demo_v2")
    if not approved:
        raise ValueError("APPROVED_ACADEMIC_DEMO_V2_MODEL_REQUIRED")
    manifest_sha = ai_runtime._sha(approved["bundle"] / "manifest.json")
    with transaction() as db:
        model = one(db, """SELECT id,model_id,model_version,manifest_sha256 FROM app.model_versions
            WHERE domain_id='academic_demo_v2' AND manifest_sha256=:sha AND is_active""", sha=manifest_sha)
        if not model:
            raise ValueError("ACTIVE_APPROVED_ACADEMIC_DEMO_V2_MODEL_REQUIRED")
        snapshots = rows(db, """SELECT DISTINCT ON (s.research_case_id)
                s.*,c.source_case_key FROM app.feature_snapshots s
            JOIN app.research_cases c ON c.id=s.research_case_id
            WHERE c.domain_id='academic_demo_v2' AND c.data_origin='synthetic'
              AND s.domain_id='academic_demo_v2' AND s.data_origin='synthetic'
            ORDER BY s.research_case_id,s.created_at DESC""")
    if len(snapshots) != 1000:
        raise ValueError(f"ACADEMIC_DEMO_V2_LATEST_SNAPSHOT_COUNT_MUST_BE_1000_GOT_{len(snapshots)}")
    return model, snapshots


def execute(model: dict, snapshots: list[dict]) -> dict[str, int]:
    created = existing = 0
    for snapshot in snapshots:
        record = {
            "case_id": str(snapshot["research_case_id"]),
            "domain_id": snapshot["domain_id"],
            "data_origin": snapshot["data_origin"],
            "feature_schema_id": snapshot["feature_schema_id"],
            "feature_schema_version": snapshot["feature_schema_version"],
            "cutoff_day": snapshot["cutoff_day"],
            "source_completeness": snapshot["source_completeness"],
            "features": snapshot["features_json"],
        }
        result = ai_runtime.predict(record)
        if result["manifest_sha256"] != model["manifest_sha256"]:
            raise ValueError("PREDICTION_MODEL_MANIFEST_MISMATCH")
        with transaction() as db:
            prior = one(db, """SELECT id FROM app.predictions
                WHERE research_case_id=:case AND feature_snapshot_id=:snapshot AND model_version_id=:model""",
                case=snapshot["research_case_id"], snapshot=snapshot["id"], model=model["id"])
            if prior:
                existing += 1
                continue
            one(db, """INSERT INTO app.predictions(
                    research_case_id,feature_snapshot_id,model_version_id,probability,threshold,risk_label,explanation_json)
                VALUES(:case,:snapshot,:model,:probability,:threshold,:label,CAST(:explanation AS jsonb)) RETURNING id""",
                case=snapshot["research_case_id"], snapshot=snapshot["id"], model=model["id"],
                probability=result["probability"], threshold=result["threshold"], label=result["risk_label"],
                explanation=json.dumps(result["explanation"], ensure_ascii=False))
            created += 1
    return {"created_predictions": created, "existing_predictions": existing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    model, snapshots = preflight()
    if args.dry_run:
        print(json.dumps({"status": "VALIDATED_ONLY", "snapshot_count": 1000, "model_version": model["model_version"], "student_profiles_changed": False}))
        return 0
    if args.confirm != CONFIRM:
        raise ValueError("EXPLICIT_RESEARCH_PREDICTION_CONFIRMATION_REQUIRED")
    print(json.dumps({"status": "COMPLETED", **execute(model, snapshots), "student_profiles_changed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
