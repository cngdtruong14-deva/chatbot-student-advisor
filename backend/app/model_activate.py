"""Operator-only activation after reviewed local artifact placement.

Usage inside the API image after migration:
    python -m app.model_activate
    python -m app.model_activate --domain academic_demo_v2
No upload endpoint exists. This command neither downloads nor installs anything.
"""
import json
import math
from app import ai_runtime
from app.store import transaction, one, run


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def activate(domain_id="oulad"):
    approved = ai_runtime.approved_bundle(domain_id)
    if not approved:
        raise RuntimeError("MODEL_NOT_READY")
    bundle, manifest = approved["bundle"], approved["manifest"]
    if manifest["domain_id"] != domain_id:
        raise RuntimeError("MODEL_DOMAIN_MISMATCH")
    expected = read_jsonl(bundle / "smoke_expected.jsonl")
    inputs = {row["case_id"]: row for row in read_jsonl(bundle / "smoke_inputs.jsonl")}
    if len(expected) < 10 or set(inputs) != {row["case_id"] for row in expected}:
        raise RuntimeError("SMOKE_CASES_INVALID")
    tolerance = manifest["parity_absolute_tolerance"]
    explanation_reference=json.loads((bundle/'explanation_config.json').read_text())
    if len(inputs)!=len(expected):raise RuntimeError('DUPLICATE_SMOKE_CASES')
    for index,reference in enumerate(expected):
        output = ai_runtime.predict(inputs[reference["case_id"]])
        if not math.isfinite(float(reference['risk_probability'])) or abs(output["probability"] - float(reference["risk_probability"])) > tolerance or (output["risk_label"] == "at_risk") != bool(reference["alert"]):
            raise RuntimeError("SMOKE_PARITY_FAILED")
        if output['explanation'] is not None:
            contributions=[c['value'] for c in output['explanation']['contributions']]
            reference_values=explanation_reference['smoke_contributions'][index]
            if len(contributions)!=len(reference_values) or any(not math.isfinite(float(b)) or abs(a-b)>1e-5 for a,b in zip(contributions,reference_values)):
                raise RuntimeError('EXPLANATION_REFERENCE_PARITY_FAILED')
    manifest_sha = ai_runtime._sha(bundle / "manifest.json")
    with transaction() as db:
        run(db,'SELECT pg_advisory_xact_lock(280402)')
        existing=one(db,'SELECT manifest_sha256 FROM app.model_versions WHERE bundle_name=:name',name=bundle.name)
        if existing and existing['manifest_sha256']!=manifest_sha: raise RuntimeError('IMMUTABLE_MODEL_VERSION_CONFLICT')
        run(db, "UPDATE app.model_versions SET is_active=false WHERE domain_id=:domain AND target_id=:target AND feature_schema_version=:schema AND cutoff_day=:cutoff", domain=manifest["domain_id"], target=manifest["target_id"], schema=manifest["feature_schema_version"], cutoff=manifest["cutoff_day"])
        model = one(db, """INSERT INTO app.model_versions(model_id,model_version,bundle_name,manifest_sha256,manifest_json,domain_id,target_id,feature_schema_version,cutoff_day,activated_by,is_active)
          VALUES(:model_id,:model_version,:bundle,:sha,CAST(:manifest AS jsonb),:domain,:target,:schema,:cutoff,:owner,true)
          ON CONFLICT(bundle_name) DO UPDATE SET is_active=true RETURNING id,model_id,model_version,bundle_name,is_active""",
          model_id=manifest["model_id"], model_version=manifest["model_version"], bundle=bundle.name, sha=manifest_sha, manifest=json.dumps(manifest), domain=manifest["domain_id"], target=manifest["target_id"], schema=manifest["feature_schema_version"], cutoff=manifest["cutoff_day"], owner=approved.get("receipt", {}).get("owner", "local-owner"))
    return model


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Activate an approved local model after smoke parity.")
    parser.add_argument("--domain", default="oulad", choices=sorted(ai_runtime.ACTIVE_RECEIPT_BY_DOMAIN))
    args = parser.parse_args()
    print(json.dumps(activate(args.domain), default=str))
