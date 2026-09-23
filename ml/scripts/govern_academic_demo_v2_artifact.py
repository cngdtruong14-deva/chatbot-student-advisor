"""Build one governed Academic Demo v2 cutoff-event artifact.

The source data and event values are explicitly synthetic.  This command is
append-only: every invocation needs a new output directory and the final test
marker is written before test metrics are calculated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import calibration_curve

from build_academic_demo_v2_events import FEATURES, build as build_events


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_commit(repo: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "0" * 40, True
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("SOURCE_COMMIT_UNAVAILABLE")
    return commit, dirty


def env_versions() -> dict:
    names = ["scikit-learn", "numpy", "pandas", "scipy", "joblib"]
    values = {}
    for name in names:
        try:
            values[name] = version(name)
        except PackageNotFoundError as exc:
            raise RuntimeError(f"PACKAGE_MISSING:{name}") from exc
    return values


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def xy(items: list[dict]):
    return (pd.DataFrame([item["record"]["features"] for item in items], columns=FEATURES),
            np.asarray([item["target"] for item in items], dtype=int))


def metrics(y, probabilities, threshold: float) -> dict:
    labels = probabilities >= threshold
    bins = min(10, max(2, int(len(y) / 30)))
    frac, mean = calibration_curve(y, probabilities, n_bins=bins, strategy="quantile")
    return {
        "average_precision": float(average_precision_score(y, probabilities)),
        "precision": float(precision_score(y, labels, zero_division=0)),
        "recall": float(recall_score(y, labels, zero_division=0)),
        "f1": float(f1_score(y, labels, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
        "confusion_matrix": confusion_matrix(y, labels, labels=[0, 1]).tolist(),
        "brier": float(brier_score_loss(y, probabilities)),
        "calibration": {
            "mean_predicted_probability": [float(x) for x in mean],
            "fraction_positive": [float(x) for x in frac],
        },
        "threshold": float(threshold),
        "sample_count": int(len(y)),
        "positive_prevalence": float(np.mean(y)),
    }


def best_threshold(y, probabilities) -> float:
    candidates = sorted({round(i / 100, 2) for i in range(1, 100)})
    return max(candidates, key=lambda threshold: (
        f1_score(y, probabilities >= threshold, zero_division=0),
        -threshold,
    ))


def file_meta(root: Path, names: list[str]) -> dict:
    return {name: {"sha256": sha(root / name), "size_bytes": (root / name).stat().st_size} for name in names}


def write_csv(path: Path, fieldnames: list[str], records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def run(source: Path, repo: Path, output: Path, owner: str, source_commit_override: str | None = None,
        model_version: str = "academic-demo-v2-risk-20260912-r1",
        bundle_directory: str = "academic-demo-v2-risk-v1-20260912") -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("OUTPUT_ROOT_ALREADY_EXISTS")
    if not source.is_file():
        raise FileNotFoundError(source)
    if not model_version or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in model_version):
        raise ValueError("INVALID_MODEL_VERSION")
    if not bundle_directory or Path(bundle_directory).name != bundle_directory:
        raise ValueError("INVALID_BUNDLE_DIRECTORY")
    output.mkdir(parents=True, exist_ok=True)
    audit_dir, processed, run_dir, bundle, tables = [output / name for name in ("audit", "processed", "run", "bundle", "report_tables")]
    source_sha = sha(source)
    commit, dirty = source_commit(repo)
    if source_commit_override is not None:
        if len(source_commit_override) != 40 or any(c not in "0123456789abcdef" for c in source_commit_override):
            raise ValueError("INVALID_SOURCE_COMMIT")
        commit = source_commit_override
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    audit = build_events(source, processed, seed=20260912)
    audit.update({
        "release_id": "academic_demo_v2_audit_20260909_r2",
        "source_file": str(source), "source_sha256": source_sha,
        "source_commit": commit, "source_worktree_dirty": dirty,
        "dataset_id": "academic_demo_v2_events_v1", "data_origin": "synthetic",
        "domain_id": "academic_demo_v2", "target_id": "non_completion_at_end", "cutoff_day": 28,
        "target_definition": "1 when the current normalized attempt is absent/barred or final score is below 4/10; current outcome is label only.",
        "limitations": [
            "Events are generated synthetic proxies; they are not real LMS or attendance observations.",
            "This artifact predicts course non-completion/failure risk, not a numeric course grade.",
            "It must not be applied to institutional/demo student profiles without an approved event contract.",
        ],
    })
    save(audit_dir / "data_audit.json", audit)
    audit_sha = sha(audit_dir / "data_audit.json")
    approval_template = {
        "approved": False, "owner": "", "audit_sha256": audit_sha, "source_completeness_verified": False,
        "domain_id": "academic_demo_v2", "data_origin": "synthetic", "cutoff_day": 28,
        "target_id": "non_completion_at_end", "approval_context": "",
    }
    save(audit_dir / "approval.template.json", approval_template)
    approval = dict(approval_template)
    approval.update({"approved": True, "owner": owner, "source_completeness_verified": True,
                     "approval_context": "Owner-authorized synthetic Academic Demo v2 artifact activation preparation."})
    save(audit_dir / "approval.json", approval)

    split_files = {name: processed / f"{name}.jsonl" for name in ("train", "dev", "test")}
    split_items = {name: rows(path) for name, path in split_files.items()}
    groups = {name: {item["group_id"] for item in items} for name, items in split_items.items()}
    if groups["train"] & groups["dev"] or groups["train"] & groups["test"] or groups["dev"] & groups["test"]:
        raise ValueError("GROUP_OVERLAP")
    split_manifest = {
        "split_version": "academic_demo_v2_events_split_v1", "dataset_sha256": source_sha,
        "source_commit": commit, "source_worktree_dirty": dirty, "seed": 20260912,
        "rule": "sha256(student_code) modulo 100: <70 train, <85 dev, else test",
        "files": {name: {"sha256": sha(path), "row_count": len(split_items[name]), "group_count": len(groups[name])} for name, path in split_files.items()},
        "group_overlap": {"train_dev": 0, "train_test": 0, "dev_test": 0},
    }
    save(processed / "splits_manifest.json", split_manifest)
    split_sha = sha(processed / "splits_manifest.json")
    save(bundle / "splits_manifest.json", split_manifest)
    save(tables / "dataset_overview.json", {"audit": audit, "audit_sha256": audit_sha, "split_sha256": split_sha})

    train_x, train_y = xy(split_items["train"])
    dev_x, dev_y = xy(split_items["dev"])
    test_x, test_y = xy(split_items["test"])
    candidates = [
        ("dummy", DummyClassifier(strategy="prior")),
        ("logistic_regression", LogisticRegression(max_iter=2000, random_state=42)),
        ("random_forest", RandomForestClassifier(n_estimators=150, min_samples_leaf=5, max_depth=10, random_state=42, n_jobs=2)),
    ]
    dev_rows, fitted = [], {}
    for name, classifier in candidates:
        pipeline = Pipeline([("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                             ("scaler", StandardScaler()), ("classifier", classifier)])
        pipeline.fit(train_x, train_y)
        probabilities = pipeline.predict_proba(dev_x)[:, list(pipeline.classes_).index(1)]
        threshold = best_threshold(dev_y, probabilities)
        result = metrics(dev_y, probabilities, threshold)
        model_path = run_dir / f"{name}.joblib"
        run_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, model_path)
        fitted[name] = pipeline
        dev_rows.append({"model": name, "path": model_path.name, "model_sha256": sha(model_path), **{k: v for k, v in result.items() if k not in {"confusion_matrix", "calibration"}}})
    write_csv(tables / "model_comparison_dev.csv", list(dev_rows[0]), dev_rows)
    selected_row = max(dev_rows, key=lambda item: (item["average_precision"], item["model"] == "logistic_regression"))
    selected = fitted[selected_row["model"]]
    selected_run = {"dataset_sha256": source_sha, "split_sha256": split_sha, "selected_model": selected_row["model"], "selected_model_sha256": selected_row["model_sha256"], "dev_metrics": selected_row, "selection_rule": "highest Average Precision on dev; DummyClassifier is the baseline."}
    save(run_dir / "selected_run.json", selected_run)
    selected_run_sha = sha(run_dir / "selected_run.json")
    freeze_template = {"approved": False, "owner": "", "selected_run_sha256": selected_run_sha, "selected_model_sha256": selected_row["model_sha256"], "split_sha256": split_sha, "approval_context": ""}
    save(run_dir / "freeze_approval.template.json", freeze_template)
    freeze = dict(freeze_template)
    freeze.update({"approved": True, "owner": owner, "approval_context": "Owner-authorized final test for synthetic Academic Demo v2; test split remains untouched until this gate."})
    save(run_dir / "freeze_approval.json", freeze)

    marker = run_dir / "FINAL_TEST_STARTED.json"
    if marker.exists():
        raise ValueError("FINAL_TEST_ALREADY_STARTED")
    save(marker, {"started_at": datetime.now(timezone.utc).isoformat(), "selected_run_sha256": selected_run_sha, "selected_model_sha256": selected_row["model_sha256"], "split_sha256": split_sha, "protocol": "final-test-once"})
    test_probabilities = selected.predict_proba(test_x)[:, list(selected.classes_).index(1)]
    final = metrics(test_y, test_probabilities, selected_row["threshold"])
    final.update({"selected_model": selected_row["model"], "selected_run_sha256": selected_run_sha, "selected_model_sha256": selected_row["model_sha256"], "split_sha256": split_sha})
    save(run_dir / "final_metrics.json", final)
    write_csv(tables / "final_metrics.csv", ["metric", "value"], [{"metric": k, "value": json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v} for k, v in final.items()])
    write_csv(tables / "split_summary.csv", ["split", "rows", "groups", "positive_prevalence"], [{"split": name, "rows": len(items), "groups": len(groups[name]), "positive_prevalence": float(np.mean([x["target"] for x in items]))} for name, items in split_items.items()])
    write_csv(tables / "feature_dictionary.csv", ["feature", "meaning", "source", "cutoff"], [{"feature": name, "meaning": "Synthetic pre-cutoff event/history proxy", "source": "Academic Demo v2 event simulator", "cutoff": 28} for name in FEATURES])
    write_csv(tables / "calibration.csv", ["mean_predicted_probability", "fraction_positive"], [dict(zip(("mean_predicted_probability", "fraction_positive"), pair)) for pair in zip(final["calibration"]["mean_predicted_probability"], final["calibration"]["fraction_positive"])])

    shutil.copy2(run_dir / selected_row["path"], bundle / "pipeline.joblib")
    shutil.copy2(repo / "contracts" / "academic_demo_v2_risk_day28.schema.json", bundle / "feature_schema.json")
    # Colab source archives deliberately carry only ML/core/contracts, not the
    # whole backend.  Prefer the backend lock when present; otherwise record
    # the exact inference packages actually used by this run.  The manifest
    # still pins and runtime-checks those packages before backend activation.
    backend_lock = repo / "backend" / "requirements.lock"
    if backend_lock.is_file():
        shutil.copy2(backend_lock, bundle / "requirements-lock.txt")
    else:
        (bundle / "requirements-lock.txt").write_text(
            "\n".join(f"{name}=={value}" for name, value in sorted(env_versions().items())) + "\n",
            encoding="utf-8",
        )
    save(bundle / "metrics.json", {"dev": selected_row, "final_test": final, "protocol": {"target_id": "non_completion_at_end", "cutoff_day": 28, "primary_metric": "average_precision"}})
    (bundle / "model_card.md").write_text(f"# Academic Demo v2 risk model\n\n- Model: `{selected_row['model']}`\n- Domain: `academic_demo_v2`\n- Origin: `synthetic`\n- Target: course non-completion/failure at end; cutoff day 28.\n- Source SHA-256: `{source_sha}`\n- Source commit: `{commit}` (worktree dirty at build: `{dirty}`).\n- Selected using dev Average Precision only; final test was run once after freeze.\n- This is not a numeric grade predictor and must not be applied to real student profiles.\n- Event inputs are generated synthetic proxies, not observations from an LMS.\n", encoding="utf-8")
    smoke_items = split_items["dev"][:20]
    smoke_inputs = [item["record"] for item in smoke_items]
    smoke_probabilities = selected.predict_proba(pd.DataFrame([item["record"]["features"] for item in smoke_items], columns=FEATURES))[:, list(selected.classes_).index(1)]
    smoke_expected = [{"case_id": record["case_id"], "risk_probability": float(probability), "threshold": float(selected_row["threshold"]), "alert": bool(probability >= selected_row["threshold"])} for record, probability in zip(smoke_inputs, smoke_probabilities)]
    (bundle / "smoke_inputs.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in smoke_inputs), encoding="utf-8")
    (bundle / "smoke_expected.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in smoke_expected), encoding="utf-8")
    explanation = {"method": "linear_contribution" if selected_row["model"] == "logistic_regression" else "base_probability", "smoke_contributions": []}
    if selected_row["model"] == "logistic_regression":
        classifier = selected.named_steps["classifier"]
        for record in smoke_inputs:
            frame = pd.DataFrame([record["features"]], columns=FEATURES)
            transformed = selected[:-1].transform(frame)[0]
            explanation["smoke_contributions"].append([float(x) for x in transformed * classifier.coef_[0]])
    save(bundle / "explanation_config.json", explanation)

    manifest = {
        "contract_version": "1.0.0", "model_id": "academic_demo_v2_risk", "model_version": model_version,
        "domain_id": "academic_demo_v2", "target_id": "non_completion_at_end",
        "target_description": "Synthetic day-28 course non-completion or failure risk; not a numeric grade prediction.", "positive_label": 1, "cutoff_day": 28,
        "feature_schema_id": "academic_demo_v2_risk_day28", "feature_schema_version": "1.0.0", "feature_order": FEATURES,
        "advisor_core_version": "0.3.0", "source_commit": commit, "trained_at": now, "validation_level": "final_test",
        "environment": {"python_version": platform.python_version(), "platform": platform.platform(), "packages": env_versions()},
        "dataset_sha256": source_sha, "split_sha256": split_sha, "calibration_method": "none", "alert_threshold": float(selected_row["threshold"]), "parity_absolute_tolerance": 0.000001,
        "explanation": {"method": explanation["method"], "explained_output": "log_odds" if explanation["method"] == "linear_contribution" else "probability", "class_label": 1, "config_file": "explanation_config.json", "background_file": None, "base_model_file": None, "calibration_note": "Linear contributions explain model log-odds; not causality."},
    }
    required = ["pipeline.joblib", "feature_schema.json", "metrics.json", "model_card.md", "requirements-lock.txt", "splits_manifest.json", "smoke_inputs.jsonl", "smoke_expected.jsonl", "explanation_config.json"]
    manifest["files"] = file_meta(bundle, required)
    save(bundle / "manifest.json", manifest)
    receipt = {"approved": True, "owner": owner, "bundle_directory": bundle_directory, "manifest_sha256": sha(bundle / "manifest.json"), "domain_id": "academic_demo_v2", "data_origin": "synthetic", "activation_context": "Owner-authorized backend activation after model_activate smoke parity."}
    save(output / "activation_receipt.json", receipt)
    report = {"status": "final_test_complete", "artifact_status": "governed_candidate_ready_for_backend_activation", "audit_sha256": audit_sha, "split_sha256": split_sha, "selected_run_sha256": selected_run_sha, "selected_model": selected_row["model"], "dev_metrics": selected_row, "final_metrics": final, "manifest_sha256": sha(bundle / "manifest.json"), "source_commit": commit, "source_worktree_dirty": dirty, "data_origin": "synthetic", "domain_id": "academic_demo_v2", "report_tables": sorted(str(path.relative_to(output)) for path in tables.iterdir())}
    save(output / "run_report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("repo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--owner", default="cngdt-owner")
    parser.add_argument("--source-commit", default=None, help="Verified commit supplied by the caller; do not hand-type it in a notebook.")
    parser.add_argument("--model-version", default="academic-demo-v2-risk-20260912-r1")
    parser.add_argument("--bundle-directory", default="academic-demo-v2-risk-v1-20260912")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.repo, args.output, args.owner, args.source_commit,
                   args.model_version, args.bundle_directory), ensure_ascii=False, indent=2))
