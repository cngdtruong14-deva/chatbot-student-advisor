"""Portable backend/Colab boundary. No database, environment secrets or model training.

Day 28 remains a candidate until the owner accepts the actual OULAD audit.
The normalized-event adapter must be audited against the real source CSVs.
"""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from types import MappingProxyType

FEATURE_ORDER = (
    "num_of_prev_attempts", "studied_credits", "vle_clicks_0_28", "vle_active_days_0_28",
    "assessment_submitted_count_0_28", "days_since_last_vle_activity",
)
COMPATIBILITY = {"domain_id": "oulad", "target_id": "non_completion_at_end",
                 "feature_schema_id": "oulad_risk_day28", "feature_schema_version": "1.0.0", "cutoff_day": 28}

# Keep the original OULAD constants above as the backwards-compatible public
# surface used by the Colab notebooks.  New model domains must be explicitly
# registered here; a manifest is never allowed to select an arbitrary schema
# or feature order supplied by an artifact.
ACADEMIC_DEMO_V2_FEATURE_ORDER = (
    "prior_gpa_4", "prior_attempts", "attendance_rate_0_28",
    "missed_sessions_0_28", "submission_rate_0_28",
    "published_assessment_mean_0_28", "lms_active_days_0_28",
)
ACADEMIC_DEMO_V2_COMPATIBILITY = {
    "domain_id": "academic_demo_v2",
    "target_id": "non_completion_at_end",
    "feature_schema_id": "academic_demo_v2_risk_day28",
    "feature_schema_version": "1.0.0",
    "cutoff_day": 28,
}

_MODEL_PROFILES = MappingProxyType({
    "oulad": MappingProxyType({
        "compatibility": MappingProxyType(COMPATIBILITY),
        "feature_order": FEATURE_ORDER,
        "schema_file": "oulad_features_v1.schema.json",
        "data_origins": frozenset({"public_dataset", "synthetic"}),
    }),
    "academic_demo_v2": MappingProxyType({
        "compatibility": MappingProxyType(ACADEMIC_DEMO_V2_COMPATIBILITY),
        "feature_order": ACADEMIC_DEMO_V2_FEATURE_ORDER,
        "schema_file": "academic_demo_v2_risk_day28.schema.json",
        "data_origins": frozenset({"synthetic"}),
    }),
})


def model_profile(domain_id):
    """Return the immutable, application-owned profile for a supported domain.

    The profile is deliberately selected from code rather than from the model
    manifest.  This prevents an approved-looking artifact from changing its
    feature contract merely by naming a different schema file.
    """
    try:
        return _MODEL_PROFILES[domain_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("MODEL_DOMAIN_MISMATCH") from exc


def profile_for_manifest(manifest):
    """Resolve a supported profile only after the manifest domain is known."""
    return model_profile(manifest.get("domain_id"))


def build_features(domain_id, raw_records, cutoff, source_completeness):
    """Build candidate features from normalized public events, never DEMO profiles.

    raw_records: case_id, data_origin, static (registration_day, withdrawal_day,
    num_of_prev_attempts, studied_credits), vle [{day,sum_click}],
    assessments [{assessment_id,submitted_day,is_banked,is_exam}].
    No score/label field is consumed. Sources must have been checked complete.
    """
    if domain_id != "oulad" or cutoff != 28:
        raise ValueError("MODEL_DOMAIN_MISMATCH")
    if set(source_completeness) != {"static_verified", "vle_complete", "assessment_complete"} or any(v is not True for v in source_completeness.values()):
        raise ValueError("INSUFFICIENT_FEATURES")
    static = raw_records["static"]
    registration = static["registration_day"]
    withdrawal = static["withdrawal_day"]
    if not isinstance(registration, int) or isinstance(registration, bool) or registration > cutoff:
        raise ValueError("POPULATION_NOT_ELIGIBLE")
    if withdrawal is not None and (not isinstance(withdrawal, int) or isinstance(withdrawal, bool) or withdrawal <= cutoff):
        raise ValueError("POPULATION_NOT_ELIGIBLE")
    clicks, days = 0, set()
    for event in raw_records["vle"]:
        day, count = event["day"], event["sum_click"]
        if type(day) is not int or type(count) is not int or count < 0:
            raise ValueError("INVALID_EVENT")
        if 0 <= day <= cutoff and count:
            clicks += count
            days.add(day)
    submitted = set()
    for event in raw_records["assessments"]:
        if type(event["submitted_day"]) is not int or type(event["is_banked"]) is not bool or type(event["is_exam"]) is not bool:
            raise ValueError("INVALID_EVENT")
        if 0 <= event["submitted_day"] <= cutoff and not event["is_banked"] and not event["is_exam"]:
            submitted.add(str(event["assessment_id"]))
    return {"case_id": raw_records["case_id"], "domain_id": domain_id, "data_origin": raw_records["data_origin"],
            "feature_schema_id": COMPATIBILITY["feature_schema_id"], "feature_schema_version": "1.0.0",
            "cutoff_day": cutoff, "source_completeness": dict(source_completeness), "features": {
                "num_of_prev_attempts": static["num_of_prev_attempts"], "studied_credits": static["studied_credits"],
                "vle_clicks_0_28": clicks, "vle_active_days_0_28": len(days),
                "assessment_submitted_count_0_28": len(submitted),
                "days_since_last_vle_activity": cutoff-max(days) if days else None}}


def validate_features(record, schema_path, *, allow_synthetic=False):
    from jsonschema import Draft202012Validator
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(record)
    profile = model_profile(record.get("domain_id"))
    if record["data_origin"] not in profile["data_origins"]:
        raise ValueError("MODEL_DOMAIN_MISMATCH")
    # Synthetic OULAD fixtures are confined to research/test paths.  Academic
    # Demo v2 is itself a clearly labelled synthetic domain and is therefore
    # validated through its own explicit profile instead of this exception.
    if record["domain_id"] == "oulad" and record["data_origin"] != "public_dataset" and not allow_synthetic:
        raise ValueError("SYNTHETIC_NOT_RESEARCH")
    for value in record["features"].values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("NON_FINITE_FEATURE")
    return [record["features"][name] for name in profile["feature_order"]]


def verify_bundle_files(bundle_path, manifest_schema_path):
    """Inspection only. Hash validity is NOT trust and does NOT permit unpickling.

    Does not deserialize a pipeline, execute bundle code, install dependencies,
    activate a model or claim parity. Reject symlinks and path traversal.
    """
    from jsonschema import Draft202012Validator, FormatChecker
    root = Path(bundle_path).resolve(strict=True)
    manifest_file = root / "manifest.json"
    if manifest_file.is_symlink() or manifest_file.stat().st_size > 1_000_000:
        raise ValueError("UNSAFE_MANIFEST")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NON_FINITE_JSON")))
    schema = json.loads(Path(manifest_schema_path).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
    profile = profile_for_manifest(manifest)
    for key, expected in profile["compatibility"].items():
        if manifest[key] != expected:
            raise ValueError("MODEL_DOMAIN_MISMATCH")
    if manifest["feature_order"] != list(profile["feature_order"]):
        raise ValueError("FEATURE_ORDER_MISMATCH")
    from importlib.metadata import version
    if manifest["advisor_core_version"] != version("sic-advisor-core"):
        raise ValueError("CORE_VERSION_MISMATCH")
    for name, metadata in manifest["files"].items():
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or "\\" in name or ":" in name:
            raise ValueError("UNSAFE_ARTIFACT_PATH")
        candidate = root.joinpath(*parts.parts)
        if any(p.is_symlink() for p in [candidate, *candidate.parents] if p != root.parent):
            raise ValueError("UNSAFE_ARTIFACT_PATH")
        target = candidate.resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size != metadata["size_bytes"]:
            raise ValueError("ARTIFACT_SIZE_OR_PATH_MISMATCH")
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != metadata["sha256"]:
            raise ValueError("ARTIFACT_HASH_MISMATCH")
    return {"status": "files_verified_only", "model_ready": False, "model_id": manifest["model_id"],
            "remaining_gates": ["trusted_origin_approval", "dataset_cutoff_audit", "runtime_environment_compatibility",
                                "positive_class_mapping", "smoke_parity", "explanation_binding", "activation_transaction"]}
