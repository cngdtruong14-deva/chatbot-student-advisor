"""Phase D: Independent Benchmark Evaluation Runner.

Evaluates Retrieval (BM25, Dense E5, Hybrid RRF) and Generation (Gemini LLM)
across Dev and Test splits with rigorous Quality Gates.

Fix notes (2026-09-19):
  Bug 1 - Scope leakage: citations from knowledge.search() do NOT carry a 'scope'
    field because evidence_response() in advisor_core.rag does not propagate it.
    All chunks are pre-filtered by accessible_chunks(corpus_scope=...) so every
    retrieved chunk is already scoped correctly.  Real scope leakage = a
    non-answerable question where the LLM generates a completed answer instead
    of abstaining (crosses scope boundary by inventing an answer out of context).
  Bug 2 - Abstention: knowledge.search() returns status='insufficient_evidence'
    when generation is not completed. Must check status field, not retrieval_status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from advisor_core.rag import lexical_search
from app.knowledge import accessible_chunks, search
from app.dense_runtime import search as dense_search
from app.llm_runtime import OpenAICompatibleProvider, config_from_env


def compute_rrf(lex_results: List[Dict], dense_results: List[Dict], k_rrf: int = 60, top_k: int = 5) -> List[Dict]:
    """Reciprocal Rank Fusion of Lexical and Dense search results."""
    scores: Dict[str, float] = {}
    chunk_map: Dict[str, Dict] = {}

    for rank, r in enumerate(lex_results):
        cid = r["chunk"]["chunk_id"]
        chunk_map[cid] = r["chunk"]
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k_rrf + rank + 1))

    for rank, r in enumerate(dense_results):
        cid = r["chunk"]["chunk_id"]
        chunk_map[cid] = r["chunk"]
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k_rrf + rank + 1))

    sorted_cids = sorted(scores.keys(), key=lambda c: (-scores[c], c))[:top_k]
    return [{"chunk": chunk_map[cid], "score": scores[cid]} for cid in sorted_cids]


def evaluate_single_turn(
    question: str,
    actual_answer: str,
    reference_answer: str,
    retrieved_chunks: List[Dict],
    gold_chunk_ids: List[str],
    required_conditions: List[str] | None = None,
    forbidden_assertions: List[str] | None = None,
    is_infra_error: bool = False,
) -> Dict[str, Any]:
    if is_infra_error:
        return {
            "passed": False,
            "has_forbidden": False,
            "has_required": False,
            "is_infra_error": True,
            "reason": "Infrastructure error (timeout/rate-limited/connection failed)",
        }

    has_forbidden = False
    if forbidden_assertions:
        has_forbidden = any(fa.strip().lower() in actual_answer.lower() for fa in forbidden_assertions if fa.strip())

    has_required = True
    if required_conditions:
        has_required = all(rc.strip().lower() in actual_answer.lower() for rc in required_conditions if rc.strip())

    passed = (not has_forbidden) and has_required
    return {
        "passed": passed,
        "has_forbidden": has_forbidden,
        "has_required": has_required,
        "is_infra_error": False,
    }


def evaluate_benchmark(
    questions_file: Path,
    split: str = "dev",
    retrieval_only: bool = False,
    freeze_approval_file: Path | None = None,
    output_file: Path | None = None,
) -> Dict[str, Any]:
    print(f"=== [PHASE D] Running Benchmark Evaluation ===")
    print(f"Questions File: {questions_file}")
    print(f"Split: {split}")
    print(f"Retrieval Only: {retrieval_only}")

    # Enforce freeze approval if running test split
    if split == "test":
        if not freeze_approval_file or not freeze_approval_file.exists():
            raise ValueError("FROZEN_RAG_CONFIG_APPROVAL_REQUIRED: Running test split requires explicit freeze approval file.")
        approval_data = json.loads(freeze_approval_file.read_text(encoding="utf-8"))
        if not approval_data.get("approved"):
            raise ValueError("FROZEN_APPROVAL_NOT_SIGNED: Test split cannot be consumed before owner sign-off.")

    # Load questions
    raw_lines = questions_file.read_text(encoding="utf-8").strip().split("\n")
    all_questions = [json.loads(line) for line in raw_lines if line.strip()]
    questions = [q for q in all_questions if q.get("split") == split]
    print(f"Loaded {len(questions)} questions for split '{split}'")

    # Load active corpus chunks
    corpus_scope = "utt_corpus"
    chunks = accessible_chunks(corpus_scope=corpus_scope)
    print(f"Accessible active release chunks: {len(chunks)}")
    if not chunks:
        raise ValueError("NO_ACTIVE_CHUNKS_FOUND: Active corpus release has 0 accessible chunks.")

    ans_questions = [q for q in questions if q["benchmark_category"] == "answerable"]
    ins_questions = [q for q in questions if q["benchmark_category"] == "insufficient_evidence"]
    scp_questions = [q for q in questions if q["benchmark_category"] == "scope_or_version"]

    results_per_question: List[Dict[str, Any]] = []

    # Method-specific metrics
    method_metrics = {
        "bm25": {"hit1": 0, "hit3": 0, "hit5": 0, "mrr5": 0.0, "recall5": 0.0, "latencies": []},
        "dense": {"hit1": 0, "hit3": 0, "hit5": 0, "mrr5": 0.0, "recall5": 0.0, "latencies": []},
        "hybrid": {"hit1": 0, "hit3": 0, "hit5": 0, "mrr5": 0.0, "recall5": 0.0, "latencies": []},
    }

    # Generation metrics
    gen_metrics = {
        "answer_correctness_count": 0,
        "citation_precision_count": 0,
        "total_claims": 0,
        "abstention_count": 0,
        "scope_leakage_count": 0,
        "total_latency": 0.0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    llm_configured = False
    if not retrieval_only:
        provider_cfg = config_from_env()
        llm_configured = provider_cfg.configured
        print(f"LLM Provider Configured: {llm_configured} (Model: {provider_cfg.model})")

    for i, q in enumerate(questions, start=1):
        qid = q.get("question_id") or q.get("id") or f"q-{i:03d}"
        q_text = q["question"]
        cat = q.get("benchmark_category") or q.get("category", "answerable")
        gold_ids = set(q.get("gold_chunk_ids", []))
        as_of = q.get("as_of", date.today().isoformat())

        row: Dict[str, Any] = {
            "question_id": qid,
            "category": cat,
            "question": q_text,
            "gold_chunk_ids": list(gold_ids),
        }

        # 1. Lexical BM25
        t0 = time.perf_counter()
        lex_candidates = lexical_search(chunks, q_text, corpus_scope, as_of, 20)
        lex_time = (time.perf_counter() - t0) * 1000
        method_metrics["bm25"]["latencies"].append(lex_time)
        lex_res = lex_candidates[:5]

        # 2. Dense E5
        t0 = time.perf_counter()
        dense_candidates = dense_search(chunks, q_text, 20)
        dense_time = (time.perf_counter() - t0) * 1000
        method_metrics["dense"]["latencies"].append(dense_time)
        dense_res = dense_candidates[:5]

        # 3. Hybrid RRF
        t0 = time.perf_counter()
        hybrid_res = compute_rrf(lex_candidates, dense_candidates, k_rrf=60, top_k=5)
        hybrid_time = (time.perf_counter() - t0) * 1000
        method_metrics["hybrid"]["latencies"].append(hybrid_time)

        retrieval_eval = {}
        for m_name, res_list in [("bm25", lex_res), ("dense", dense_res), ("hybrid", hybrid_res)]:
            found_ids = [r["chunk"]["chunk_id"] for r in res_list]
            ranks = [idx + 1 for idx, cid in enumerate(found_ids) if cid in gold_ids]
            h1 = bool(ranks and ranks[0] == 1)
            h3 = bool(ranks and ranks[0] <= 3)
            h5 = bool(ranks and ranks[0] <= 5)
            rr = 1.0 / ranks[0] if ranks else 0.0
            rec = len(set(found_ids) & gold_ids) / len(gold_ids) if gold_ids else 0.0

            if cat == "answerable":
                method_metrics[m_name]["hit1"] += int(h1)
                method_metrics[m_name]["hit3"] += int(h3)
                method_metrics[m_name]["hit5"] += int(h5)
                method_metrics[m_name]["mrr5"] += rr
                method_metrics[m_name]["recall5"] += rec

            retrieval_eval[m_name] = {
                "top1_chunk": found_ids[0] if found_ids else None,
                "ranks": ranks,
                "hit1": h1,
                "hit3": h3,
                "hit5": h5,
                "rr": rr,
                "recall": rec,
            }

        row["retrieval"] = retrieval_eval

        # 4. Generation Evaluation (if enabled)
        if not retrieval_only and llm_configured:
            t_gen0 = time.perf_counter()
            search_res = search(q_text, corpus_scope=corpus_scope)
            gen_dur = time.perf_counter() - t_gen0
            gen_metrics["total_latency"] += gen_dur

            status = search_res.get("status")
            claims = search_res.get("claims", [])
            citations = search_res.get("citations", [])

            # Evaluate Answerable
            if cat == "answerable":
                is_answered = (status == "answered")
                retrieved_cids = {c["chunk_id"] for c in citations}
                
                # Rule: claims cannot be empty if answered
                if is_answered and not claims:
                    all_claims_supported = False
                elif not is_answered:
                    all_claims_supported = False
                else:
                    all_claims_supported = True

                valid_claims_count = 0
                for cl in claims:
                    gen_metrics["total_claims"] += 1
                    cids = cl.get("citation_ids", [])
                    if cids and set(cids).issubset(retrieved_cids):
                        valid_claims_count += 1
                        gen_metrics["citation_precision_count"] += 1
                    else:
                        all_claims_supported = False

                # Semantic rubric check against forbidden_assertions and required_conditions
                full_ans = search_res.get("answer") or ""
                has_forbidden = False
                for fa in q.get("forbidden_assertions", []):
                    if fa.lower() in full_ans.lower():
                        has_forbidden = True
                        break

                has_required = True
                for rc in q.get("required_conditions", []):
                    if rc.lower() not in full_ans.lower():
                        has_required = False
                        break

                correctness = bool(is_answered and all_claims_supported and not has_forbidden and has_required)
                if correctness:
                    gen_metrics["answer_correctness_count"] += 1

                row["generation"] = {
                    "status": status,
                    "is_answered": is_answered,
                    "claims_count": len(claims),
                    "valid_claims_count": valid_claims_count,
                    "all_claims_supported": all_claims_supported,
                    "has_forbidden": has_forbidden,
                    "has_required": has_required,
                    "correctness": correctness,
                    "full_answer": full_ans,
                    "claims": claims,
                    "citations": citations,
                    "actual_model": search_res.get("model") or os.environ.get("RAG_LLM_MODEL", "unknown"),
                    "latency": round(gen_dur, 2),
                }

            # Evaluate Non-Answerable (Insufficient Evidence & Scope)
            else:
                gen_status = search_res.get("generation_status", "")
                is_infra_error = gen_status in ("timeout", "rate_limited", "authentication_error", "provider_error", "provider_unavailable")

                if is_infra_error:
                    gen_metrics["infra_error_count"] += 1
                    is_abstained = False
                else:
                    # Model genuinely and safely declined
                    is_abstained = (status == "insufficient_evidence") or (gen_status != "completed" and "chưa đủ" in (search_res.get("answer") or "").lower())
                    if is_abstained:
                        gen_metrics["abstention_count"] += 1

                scope_leak = (not is_abstained) and (not is_infra_error) and (gen_status == "completed")
                if scope_leak:
                    gen_metrics["scope_leakage_count"] += 1

                row["generation"] = {
                    "status": status,
                    "generation_status": gen_status,
                    "is_infra_error": is_infra_error,
                    "is_abstained": is_abstained,
                    "scope_leak": scope_leak,
                    "full_answer": search_res.get("answer") or "",
                    "claims": claims,
                    "citations": citations,
                    "actual_model": search_res.get("model") or os.environ.get("RAG_LLM_MODEL", "unknown"),
                    "latency": round(gen_dur, 2),
                }

        results_per_question.append(row)
        if not retrieval_only and llm_configured:
            time.sleep(1.0)
        if i % 10 == 0 or i == len(questions):
            print(f"Processed {i}/{len(questions)} questions...")

    # Calculate summary metrics
    n_ans = len(ans_questions)
    n_non_ans = len(ins_questions) + len(scp_questions)

    summary: Dict[str, Any] = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "split": split,
        "total_questions": len(questions),
        "composition": {
            "answerable": n_ans,
            "insufficient_evidence": len(ins_questions),
            "scope_or_version": len(scp_questions),
        },
        "retrieval_metrics": {},
        "quality_gates": {},
    }

    for m_name in ["bm25", "dense", "hybrid"]:
        m_data = method_metrics[m_name]
        lats = m_data["latencies"]
        summary["retrieval_metrics"][m_name] = {
            "hit_at_1": round(m_data["hit1"] / n_ans, 4) if n_ans else 0.0,
            "hit_at_3": round(m_data["hit3"] / n_ans, 4) if n_ans else 0.0,
            "hit_at_5": round(m_data["hit5"] / n_ans, 4) if n_ans else 0.0,
            "mrr_at_5": round(m_data["mrr5"] / n_ans, 4) if n_ans else 0.0,
            "recall_at_5": round(m_data["recall5"] / n_ans, 4) if n_ans else 0.0,
            "latency_p50_ms": round(sorted(lats)[len(lats) // 2], 2) if lats else 0.0,
            "latency_p95_ms": round(sorted(lats)[int(len(lats) * 0.95)], 2) if lats else 0.0,
        }

    # Quality Gate Checks (Based on Section 7.2 of plan)
    best_hit5 = summary["retrieval_metrics"]["hybrid"]["hit_at_5"]
    best_mrr = summary["retrieval_metrics"]["hybrid"]["mrr_at_5"]

    summary["quality_gates"]["gate_retrieval_hit5_gte_90"] = bool(best_hit5 >= 0.90)
    summary["quality_gates"]["gate_mrr5_gte_075"] = bool(best_mrr >= 0.75)
    summary["quality_gates"]["gate_scope_leakage_zero"] = bool(gen_metrics["scope_leakage_count"] == 0)

    if not retrieval_only and llm_configured:
        ans_corr = gen_metrics["answer_correctness_count"] / n_ans if n_ans else 0.0
        abst_acc = gen_metrics["abstention_count"] / n_non_ans if n_non_ans else 0.0
        cit_prec = gen_metrics["citation_precision_count"] / max(1, gen_metrics["total_claims"])
        avail_rate = (len(questions) - gen_metrics["infra_error_count"]) / max(1, len(questions))

        summary["generation_metrics"] = {
            "answer_correctness": round(ans_corr, 4),
            "abstention_accuracy": round(abst_acc, 4),
            "citation_support_precision": round(cit_prec, 4),
            "scope_leakage_count": gen_metrics["scope_leakage_count"],
            "infra_error_count": gen_metrics["infra_error_count"],
            "availability_rate": round(avail_rate, 4),
            "avg_latency_seconds": round(gen_metrics["total_latency"] / max(1, len(questions)), 2),
        }
        summary["quality_gates"]["gate_answer_correctness_gte_90"] = bool(ans_corr >= 0.90)
        summary["quality_gates"]["gate_abstention_gte_95"] = bool(abst_acc >= 0.95)
        summary["quality_gates"]["gate_citation_precision_gte_95"] = bool(cit_prec >= 0.95)

    report = {
        "protocol": "phase_d_utt_benchmark_evaluation_v1",
        "release_id": "UTT-CORPUS-2026-V1",
        "summary": summary,
        "results": results_per_question,
    }

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Full report written to: {output_file}")

    print("\n--- BENCHMARK EVALUATION SUMMARY ---")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description="Phase D UTT Benchmark Evaluator")
    parser.add_argument("--questions", default="/artifacts/phase_d/utt_benchmark_120.jsonl")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--freeze-approval", default=None)
    parser.add_argument("--output", default="/tmp/phase_d/benchmark_results.json")

    args = parser.parse_args()
    q_path = Path(args.questions)
    if not q_path.exists():
        q_path = Path("/tmp/phase_d/utt_benchmark_120.jsonl")
    if not q_path.exists():
        q_path = Path("artifacts/phase_d/utt_benchmark_120.jsonl")

    freeze_path = Path(args.freeze_approval) if args.freeze_approval else None
    if not freeze_path or not freeze_path.exists():
        for candidate in (Path("/artifacts/phase_d/rag_freeze_approval.json"), Path("artifacts/phase_d/rag_freeze_approval.json")):
            if candidate.exists():
                freeze_path = candidate
                break
    out_path = Path(args.output)

    evaluate_benchmark(
        questions_file=q_path,
        split=args.split,
        retrieval_only=args.retrieval_only,
        freeze_approval_file=freeze_path,
        output_file=out_path,
    )


if __name__ == "__main__":
    main()
