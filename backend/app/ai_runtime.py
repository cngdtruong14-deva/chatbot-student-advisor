"""Safe runtime boundary for approved, explicitly registered model domains."""
import hashlib
import json
import math
import os
import sys
from datetime import date
from importlib.metadata import version
from pathlib import Path

from advisor_core.ml_boundary import model_profile, verify_bundle_files, validate_features
from advisor_core.rag import chunk_markdown, evidence_response, lexical_search

ROOT = Path(os.environ.get("MODEL_DIRECTORY", "/artifacts/approved"))
RESOURCES = Path(__file__).with_name("resources")

# A receipt is selected by an application-owned domain map, not by request
# data or an artifact filename.  Keeping ``active.json`` for OULAD preserves
# the pre-existing public-research integration while allowing a separate,
# clearly labelled synthetic Academic Demo v2 model to be activated.
ACTIVE_RECEIPT_BY_DOMAIN = {
    "oulad": "active.json",
    "academic_demo_v2": "academic-demo-v2-active.json",
}

class AIRuntimeError(ValueError):
    pass

def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def approved_bundle(domain_id="oulad"):
    try:
        receipt_name = ACTIVE_RECEIPT_BY_DOMAIN[domain_id]
    except (KeyError, TypeError) as exc:
        raise AIRuntimeError("MODEL_DOMAIN_MISMATCH") from exc
    receipt_path = ROOT / receipt_name
    if not receipt_path.is_file():
        return None
    receipt = _json(receipt_path)
    required = {"approved", "owner", "bundle_directory", "manifest_sha256"}
    if not required <= set(receipt) or receipt["approved"] is not True or not str(receipt["owner"]).strip():
        raise AIRuntimeError("MODEL_APPROVAL_REQUIRED")
    name = receipt["bundle_directory"]
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        raise AIRuntimeError("UNSAFE_ARTIFACT_PATH")
    root = ROOT.resolve(strict=True)
    bundle = (ROOT / name).resolve(strict=True)
    if not bundle.is_relative_to(root) or not bundle.is_dir():
        raise AIRuntimeError("UNSAFE_ARTIFACT_PATH")
    verify_bundle_files(bundle, "/contracts/model_manifest.schema.json")
    manifest_path = bundle / "manifest.json"
    if _sha(manifest_path) != receipt["manifest_sha256"]:
        raise AIRuntimeError("MODEL_APPROVAL_MANIFEST_MISMATCH")
    manifest = _json(manifest_path)
    if manifest["domain_id"] != domain_id:
        raise AIRuntimeError("MODEL_DOMAIN_MISMATCH")
    if manifest["validation_level"] != "final_test":
        raise AIRuntimeError("MODEL_FINAL_TEST_REQUIRED")
    return {"bundle": bundle, "manifest": manifest, "receipt": receipt}

def predict(record):
    try:
        profile = model_profile(record.get("domain_id"))
    except ValueError as exc:
        raise AIRuntimeError("MODEL_DOMAIN_MISMATCH")
    if record.get("data_origin") not in profile["data_origins"]:
        raise AIRuntimeError("MODEL_DOMAIN_MISMATCH")
    approved = approved_bundle(record["domain_id"])
    if not approved:
        raise AIRuntimeError("MODEL_NOT_READY")
    manifest = approved["manifest"]
    if tuple(map(int,manifest['environment']['python_version'].split('.')[:2])) != sys.version_info[:2]:
        raise AIRuntimeError('MODEL_PYTHON_MISMATCH')
    values = validate_features(
        record,
        f"/contracts/{profile['schema_file']}",
        allow_synthetic=record.get("domain_id") == "oulad" and record.get("data_origin") == "synthetic",
    )
    for package in ("scikit-learn", "numpy", "pandas", "scipy", "joblib"):
        if version(package) != manifest["environment"]["packages"][package]:
            raise AIRuntimeError("MODEL_RUNTIME_MISMATCH")
    if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)) for v in values):
        raise AIRuntimeError("INVALID_FEATURE_VECTOR")
    import joblib  # only after local approval, hash and runtime checks
    import pandas as pd
    model = joblib.load(approved["bundle"] / "pipeline.joblib")
    classes = list(getattr(model, "classes_", []))
    if 1 not in classes:
        raise AIRuntimeError("MODEL_POSITIVE_CLASS_MISMATCH")
    frame=pd.DataFrame([values], columns=list(profile["feature_order"])).astype(float)
    probability = float(model.predict_proba(frame)[0][classes.index(1)])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise AIRuntimeError("INVALID_MODEL_OUTPUT")
    explanation=None
    if manifest['explanation']['method']=='linear_contribution' and classes==[0,1]:
        clf=model.named_steps['classifier']
        transformed=model[:-1].transform(frame)[0]
        contributions=(transformed*clf.coef_[0]).tolist()
        base=float(clf.intercept_[0]);log_odds=float(model.decision_function(frame)[0])
        if abs(base+sum(contributions)-log_odds)>1e-5:raise AIRuntimeError('EXPLANATION_PARITY_FAILED')
        explanation={'method':'linear_contribution','scale':'log_odds','base_value':base,'output':log_odds,
          'contributions':[{'feature':name,'value':float(value)} for name,value in zip(profile["feature_order"],contributions)],
          'note':'Đóng góp vào log-odds của mô hình; không phải quan hệ nhân quả.'}
    return {"domain_id": manifest["domain_id"], "data_origin": record["data_origin"], "target_id": manifest["target_id"], "explanation":explanation,"manifest_sha256": _sha(approved['bundle'] / 'manifest.json'), "probability": probability, "threshold": manifest["alert_threshold"],
            "risk_label": "at_risk" if probability >= manifest["alert_threshold"] else "not_at_risk", "manifest": manifest,
            "bundle_name": approved["bundle"].name}

def rag_chunks():
    config = _json(RESOURCES / "rag_config.json")
    text = (RESOURCES / "DEMO1.md").read_text(encoding="utf-8")
    return chunk_markdown(text, document_id="demo1-policy", version_id=config["corpus_version"], scope=config["scope"],
                          source="backend:resources/DEMO1.md", valid_from=config["valid_from"], max_chars=config["max_chars"]), config

def retrieve(query, scope, as_of):
    chunks, config = rag_chunks()
    when = (as_of.date() if as_of else date.today()).isoformat()
    result = evidence_response(lexical_search(chunks, query, scope, when, config["retrieval_k"]), query)
    result.update(corpus_version=config["corpus_version"], retrieval_method="keyword", data_origin="synthetic")
    return result

def capabilities():
    def model_status(domain_id):
        try:
            approved = approved_bundle(domain_id)
            status = "approved_not_loaded"
        except (OSError, ValueError):
            return "approval_or_artifact_invalid"
        if not approved:
            return "not_configured"
        try:
            from app.store import transaction,one
            with transaction() as db:
                if one(db, 'SELECT id FROM app.model_versions WHERE manifest_sha256=:sha AND is_active', sha=_sha(approved['bundle']/'manifest.json')):
                    status='active_smoke_verified'
        except Exception:
            # Status remains truthful about a locally approved artifact even
            # when the database is temporarily unavailable.
            pass
        return status

    model = model_status("oulad")
    academic_demo_v2_model = model_status("academic_demo_v2")
    try:
        from app.knowledge import accessible_chunks
        chunks=accessible_chunks()
        rag='active_corpus' if chunks else 'corpus_not_ready'
    except Exception:
        rag='database_not_ready'
    from app.llm_runtime import provider_status
    return {"chatbot_rag": rag, "risk_model": model, "academic_demo_v2_risk_model": academic_demo_v2_model,
            "llm": provider_status(), "embedding": os.environ.get('RAG_METHOD','keyword')}
