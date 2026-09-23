"""Offline package and contract checks for the ML boundary; this does not test a model."""
import copy
import importlib.metadata
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

RUNTIME_KEYS = (
    "DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "POSTGRES_PASSWORD", "ADMIN_DB_PASSWORD", "MIGRATOR_DB_PASSWORD", "APP_DB_PASSWORD",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
)


def fail(message: str) -> int:
    print(f"[FAIL] {message}", file=sys.stderr)
    return 1


def expect_rejected(label, operation, error_types):
    try:
        operation()
    except error_types:
        print(f"[OK] Negative test rejected: {label}")
        return
    raise AssertionError(f"Negative test unexpectedly accepted: {label}")


def assert_compatible(manifest, expected_features, package_version):
    if manifest["advisor_core_version"] != package_version:
        raise ValueError("advisor_core package version mismatch")
    if manifest["domain_id"] != "oulad":
        raise ValueError("domain mismatch")
    if manifest["feature_schema_id"] != "oulad_risk_day28" or manifest["feature_schema_version"] != "1.0.0":
        raise ValueError("feature schema mismatch")
    if manifest["cutoff_day"] != 28:
        raise ValueError("cutoff must be exactly day 28")
    order = manifest["feature_order"]
    if len(order) != len(expected_features) or len(set(order)) != len(order) or set(order) != set(expected_features):
        raise ValueError("feature set must be exactly the six OULAD contract features")


def main() -> int:
    present = [key for key in RUNTIME_KEYS if key in os.environ]
    if present:
        return fail("Unexpected runtime credential names: " + ", ".join(present))
    print("[OK] No DB or LLM credential names are present.")
    try:
        import advisor_core
        import jsonschema
    except ImportError as error:
        return fail(f"Required installed package is unavailable: {error}")
    root = Path(__file__).resolve().parent.parent
    with (root / "packages" / "advisor_core" / "pyproject.toml").open("rb") as file:
        declared_package_version = tomllib.load(file)["project"]["version"]
    installed_package_version = importlib.metadata.version("sic-advisor-core")
    if installed_package_version != declared_package_version:
        return fail("Installed sic-advisor-core version differs from pyproject.toml")
    contract_version = advisor_core.CONTRACT_VERSION
    print(f"[OK] Package version: {installed_package_version}; contract version: {contract_version}")
    schemas = root / "contracts"
    manifest_schema = json.loads((schemas / "model_manifest.schema.json").read_text(encoding="utf-8"))
    feature_schema = json.loads((schemas / "oulad_features_v1.schema.json").read_text(encoding="utf-8"))
    expected_features = feature_schema["properties"]["features"]["required"]
    sha = "a" * 64
    manifest = {
        "contract_version": contract_version, "model_id": "oulad-risk-lr-v1", "model_version": "0.0.0-test",
        "domain_id": "oulad", "target_id": "non_completion_at_end", "target_description": "Synthetic test manifest for OULAD cutoff validation; not dataset approval.",
        "positive_label": 1, "cutoff_day": 28, "feature_schema_id": "oulad_risk_day28", "feature_schema_version": "1.0.0",
        "feature_order": list(expected_features), "advisor_core_version": installed_package_version,
        "source_commit": "0" * 40, "trained_at": "2026-09-06T00:00:00Z", "validation_level": "dev_only",
        "environment": {"python_version": "3.12.0", "platform": "synthetic", "packages": {"scikit-learn": "1", "numpy": "1", "pandas": "1", "scipy": "1", "joblib": "1"}},
        "dataset_sha256": sha, "split_sha256": sha, "calibration_method": "none", "alert_threshold": 0.5, "parity_absolute_tolerance": 0.0001,
        "explanation": {"method": "linear_contribution", "explained_output": "probability", "class_label": 1, "config_file": "explanation_config.json", "background_file": None, "base_model_file": None, "calibration_note": "Synthetic test only."},
        "files": {name: {"sha256": sha, "size_bytes": 1} for name in ("pipeline.joblib", "feature_schema.json", "metrics.json", "model_card.md", "requirements-lock.txt", "splits_manifest.json", "smoke_inputs.jsonl", "smoke_expected.jsonl", "explanation_config.json")},
    }
    jsonschema.validate(manifest, manifest_schema)
    assert_compatible(manifest, expected_features, installed_package_version)
    record = {
        "case_id": "synthetic", "domain_id": "oulad", "data_origin": "synthetic", "feature_schema_id": "oulad_risk_day28", "feature_schema_version": "1.0.0", "cutoff_day": 28,
        "source_completeness": {"static_verified": True, "vle_complete": True, "assessment_complete": True},
        "features": {"num_of_prev_attempts": 0, "studied_credits": 60.0, "vle_clicks_0_28": 4, "vle_active_days_0_28": 1, "assessment_submitted_count_0_28": 0, "days_since_last_vle_activity": 2},
    }
    jsonschema.validate(record, feature_schema)
    mutations = (
        ("package version", lambda x: x.update(advisor_core_version="0.0.1")),
        ("domain", lambda x: x.update(domain_id="other")),
        ("schema id", lambda x: x.update(feature_schema_id="other")),
        ("schema version", lambda x: x.update(feature_schema_version="9")),
        ("cutoff 29", lambda x: x.update(cutoff_day=29)),
        ("negative cutoff", lambda x: x.update(cutoff_day=-1)),
        ("missing features", lambda x: x.update(feature_order=list(expected_features[:-1]))),
        ("extra feature", lambda x: x.update(feature_order=list(expected_features) + ["extra"])),
        ("duplicate feature", lambda x: x.update(feature_order=list(expected_features[:-1]) + [expected_features[0]])),
    )
    for label, mutation in mutations:
        candidate = copy.deepcopy(manifest)
        mutation(candidate)
        expect_rejected(label, lambda c=candidate: assert_compatible(c, expected_features, installed_package_version), ValueError)
    invalid_record = copy.deepcopy(record)
    invalid_record["features"]["vle_active_days_0_28"] = 30
    expect_rejected("invalid OULAD record", lambda: jsonschema.validate(invalid_record, feature_schema), jsonschema.ValidationError)
    environment = dict(os.environ)
    environment["APP_DB_PASSWORD"] = "synthetic-test-value"
    probe = subprocess.run([sys.executable, '-B', __file__], env=environment, check=False, capture_output=True, text=True)
    if probe.returncode != 1 or 'Unexpected runtime credential names: APP_DB_PASSWORD' not in probe.stderr or 'synthetic-test-value' in probe.stderr:
        return fail("Credential-detection probe was unexpectedly accepted")
    missing = subprocess.run([sys.executable, '-B', '-c', "import sys,runpy; sys.modules['jsonschema']=None; runpy.run_path(sys.argv[1],run_name='__main__')", __file__], check=False, capture_output=True, text=True)
    if missing.returncode != 1 or 'Required installed package is unavailable' not in missing.stderr:
        return fail('Missing dependency did not fail for the expected reason')
    print('[OK] Missing jsonschema dependency was rejected with exit 1.')
    print("[OK] Credential-detection probe was rejected without exposing its value.")
    print("PASS: package/schema checks pass without runtime credentials; this is not model parity or network isolation.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"[FAIL] {error}")
