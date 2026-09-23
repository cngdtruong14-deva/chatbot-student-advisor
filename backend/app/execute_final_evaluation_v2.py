"""QUARANTINED legacy final evaluator.

This historical runner is deliberately blocked because it scored each benchmark
row with ``reference_answer`` instead of an answer produced by the RAG pipeline.
Its output under ``artifacts/freeze_v2`` is diagnostic-only and can never serve
as final-evaluation evidence.  Stage 6 uses ``app.rag_benchmark_v2`` with a new
immutable run namespace and a reviewed V2 protocol instead.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True)
        return out.strip()
    except Exception:
        return "UNKNOWN_COMMIT"


def resolve_file_path(rel_path: str) -> Path:
    if Path("/artifacts").exists() and Path("/app").exists():
        if rel_path.startswith("backend/"):
            return Path("/app") / rel_path[len("backend/"):]
        elif rel_path.startswith("artifacts/"):
            return Path("/artifacts") / rel_path[len("artifacts/"):]
        else:
            return Path("/") / rel_path
    else:
        return REPO_ROOT / rel_path


def verify_freeze_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Freeze manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for item in manifest.get("frozen_components", []):
        rel_path = item["path"]
        expected_sha = item["sha256"].lower()
        full_path = resolve_file_path(rel_path)

        if not full_path.exists():
            raise FileNotFoundError(f"Frozen component missing: {rel_path} (full: {full_path})")

        actual_sha = compute_sha256(full_path).lower()
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"Freeze integrity violation for {rel_path}! Expected {expected_sha}, got {actual_sha}. Execution halted."
            )

    print("All freeze manifest components verified successfully.")
    return manifest


def main():
    raise SystemExit(
        "LEGACY_FINAL_EVALUATOR_QUARANTINED: use app.rag_benchmark_v2 only after "
        "a reviewed V2 dataset and a hash-bound owner approval exist."
    )
    default_manifest = "/artifacts/freeze_v2/freeze_manifest_v2.json" if Path("/artifacts").exists() else str(REPO_ROOT / "artifacts" / "freeze_v2" / "freeze_manifest_v2.json")
    default_dataset = "/artifacts/benchmark_v2/benchmark_v2_template.jsonl" if Path("/artifacts").exists() else str(REPO_ROOT / "artifacts" / "benchmark_v2" / "benchmark_v2_template.jsonl")
    default_output = "/vectorstore/freeze_v2" if Path("/vectorstore").exists() else str(REPO_ROOT / "artifacts" / "freeze_v2")

    parser = argparse.ArgumentParser(description="Execute Benchmark Final Evaluation v2")
    parser.add_argument(
        "--manifest",
        default=default_manifest,
        help="Path to freeze manifest v2",
    )
    parser.add_argument(
        "--dataset",
        default=default_dataset,
        help="Benchmark dataset JSONL",
    )
    parser.add_argument(
        "--output-dir",
        default=default_output,
        help="Output directory for results and lifecycle tokens",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Strict SHA-256 Freeze Verification
    print(f"\n[Step 1] Verifying freeze manifest: {manifest_path}...")
    manifest = verify_freeze_manifest(manifest_path)

    # Step 2: Create Lifecycle Token FINAL_STARTED
    start_time = datetime.now(timezone.utc)
    commit_sha = get_git_commit()
    token_started_path = output_dir / "FINAL_STARTED"

    started_payload = {
        "status": "STARTED",
        "started_at": start_time.isoformat(),
        "git_commit": commit_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": compute_sha256(manifest_path),
        "dataset_path": str(dataset_path),
        "dataset_sha256": compute_sha256(dataset_path),
        "pid": os.getpid(),
    }
    with open(token_started_path, "w", encoding="utf-8") as f:
        json.dump(started_payload, f, indent=2)
    print(f"[Step 2] Lifecycle token created: {token_started_path}")

    # Step 3: Checkpoint evaluation loop
    checkpoint_file = output_dir / "final_results_checkpoint.jsonl"
    processed_ids = set()
    if checkpoint_file.exists():
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    processed_ids.add(rec.get("question_id"))
        print(f"[Step 3] Resuming from checkpoint: {len(processed_ids)} questions already evaluated.")
    else:
        print("[Step 3] Starting clean evaluation run.")

    questions = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    # Evaluate each question
    from app.evaluate_phase_d_benchmark import evaluate_single_turn
    from app.knowledge import accessible_chunks, retrieve_candidates

    chunks = accessible_chunks(corpus_scope="utt_corpus")
    start_eval = time.time()
    results = []

    with open(checkpoint_file, "a", encoding="utf-8") as out_f:
        for idx, q in enumerate(questions):
            qid = q.get("question_id", f"Q_{idx}")
            if qid in processed_ids:
                continue

            q_start = time.time()
            # Retrieve candidates using hybrid RRF
            candidates = retrieve_candidates(q["question"], chunks, method="hybrid", top_k=5)
            retrieved_ids = [c["chunk"]["chunk_id"] if "chunk" in c else c.get("chunk_id") for c in candidates]
            gold_ids = q.get("gold_chunk_ids", [])
            hit5 = 1.0 if any(g in retrieved_ids for g in gold_ids) else 0.0

            # Evaluate semantic rubric
            eval_res = evaluate_single_turn(
                question=q["question"],
                actual_answer=q.get("reference_answer", ""),
                reference_answer=q.get("reference_answer", ""),
                retrieved_chunks=[c["chunk"] if "chunk" in c else c for c in candidates],
                gold_chunk_ids=gold_ids,
                required_conditions=q.get("required_conditions", []),
                forbidden_assertions=q.get("forbidden_assertions", []),
            )
            q_latency_ms = (time.time() - q_start) * 1000.0

            item_result = {
                "question_id": qid,
                "group_id": q.get("group_id"),
                "split": q.get("split", "dev"),
                "question": q["question"],
                "hit5": hit5,
                "answer_correctness": 1.0 if eval_res.get("passed") else 0.0,
                "has_forbidden": eval_res.get("has_forbidden", False),
                "has_required": eval_res.get("has_required", True),
                "is_infra_error": eval_res.get("is_infra_error", False),
                "latency_ms": q_latency_ms,
                "actual_model": os.environ.get("RAG_LLM_MODEL", "model_provenance_not_verified"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            out_f.write(json.dumps(item_result, ensure_ascii=False) + "\n")
            out_f.flush()
            results.append(item_result)
            processed_ids.add(qid)
            print(f"  Evaluated {qid}: hit5={hit5}, passed={eval_res.get('passed')}")

    total_time = time.time() - start_eval
    print(f"\nEvaluation finished in {total_time:.2f}s.")

    # Step 4: Create Lifecycle Token FINAL_COMPLETED
    token_completed_path = output_dir / "FINAL_COMPLETED"
    checkpoint_sha = compute_sha256(checkpoint_file)

    completed_payload = {
        "status": "COMPLETED",
        "started_at": start_time.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(total_time, 2),
        "git_commit": commit_sha,
        "total_questions_evaluated": len(processed_ids),
        "results_file": str(checkpoint_file),
        "results_sha256": checkpoint_sha,
        "actual_model": os.environ.get("RAG_LLM_MODEL", "model_provenance_not_verified"),
    }
    with open(token_completed_path, "w", encoding="utf-8") as f:
        json.dump(completed_payload, f, indent=2)

    print(f"[Step 4] Lifecycle completion token created: {token_completed_path}")
    print("SUCCESS: Benchmark Final Evaluation v2 completed.")


if __name__ == "__main__":
    main()
