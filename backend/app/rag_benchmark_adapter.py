"""Shared retrieval/generation adapter and runner for RAG Benchmark V2.

Implements the unified adapter connecting knowledge.retrieve_candidates and
llm_runtime.OpenAICompatibleProvider to the fail-closed rag_benchmark_v2 protocol.
Never passes reference answers or gold evidence to the generator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

from app import knowledge
from app.llm_runtime import OpenAICompatibleProvider
from app.rag_generation_approval import (
    load_approval as load_generation_approval,
    validate_generation_approval,
)
from app.rag_benchmark_v2 import (
    PROTOCOL_VERSION,
    BenchmarkProtocolError,
    evaluate_dataset,
    load_json_object,
    load_jsonl,
    prepare_final_run,
    validate_benchmark_protocol,
    file_sha256,
)

logger = logging.getLogger("advisor.benchmark_adapter")


def _provider_matches(selected_candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Restore provider input from evaluator-safe retrieved candidate records.

    ``evaluate_dataset`` removes the nested ``chunk`` object before invoking the
    answer callback.  This conversion uses only retrieved evidence fields; gold
    chunks, reference answers and rubric conditions are never inputs.
    """
    result: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        if not isinstance(candidate, Mapping):
            continue
        if isinstance(candidate.get("chunk"), Mapping):
            result.append(dict(candidate))
            continue
        chunk_id = candidate.get("chunk_id")
        evidence_text = candidate.get("evidence_text")
        if not isinstance(chunk_id, str) or not chunk_id or not isinstance(evidence_text, str) or not evidence_text:
            continue
        result.append({
            "score": candidate.get("score"),
            "chunk": {
                "chunk_id": chunk_id,
                "text": evidence_text,
                "title": candidate.get("title"),
                "section": candidate.get("section"),
                "source": candidate.get("source"),
                "release_id": candidate.get("release_id"),
                "page_number": candidate.get("page_number"),
            },
        })
    return result


def _answer_method_from_binding(
    runtime_binding: Mapping[str, Any], methods: Sequence[str], explicit: str | None = None,
) -> str:
    """Bind generation to the retriever selected in the immutable runtime identity."""
    selected = explicit or str((runtime_binding.get("retriever") or {}).get("method") or "")
    if not selected or selected not in methods:
        raise BenchmarkProtocolError("RUNTIME_BINDING_ANSWER_METHOD_INVALID")
    return selected


def get_git_commit(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True)
        return out.strip()
    except Exception:
        return "UNKNOWN_COMMIT"


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    """Create an immutable run artifact; never overwrite or resume it."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def make_shared_retriever(
    *,
    corpus_scope: str = "utt_corpus",
    chunks_cache: list[dict] | None = None,
) -> Callable[[str, Mapping[str, Any], str, int], Sequence[Mapping[str, Any]]]:
    """Return a retrieval callback bound to the live application retriever.

    Accepts (query, context, method, top_k) from rag_benchmark_v2.evaluate_dataset.
    """
    cached_chunks = chunks_cache

    def retrieve(
        query: str,
        context: Mapping[str, Any],
        method: str,
        top_k: int,
    ) -> Sequence[Mapping[str, Any]]:
        nonlocal cached_chunks
        as_of_str = context.get("as_of")
        when = None
        if as_of_str and isinstance(as_of_str, str):
            try:
                when = datetime.fromisoformat(as_of_str).date()
            except ValueError:
                when = None

        if cached_chunks is None:
            cached_chunks = knowledge.accessible_chunks(
                as_of=datetime.combine(when, datetime.min.time()) if when else None,
                corpus_scope=corpus_scope,
            )

        matches = knowledge.retrieve_candidates(
            query=query,
            chunks=cached_chunks,
            method=method,
            top_k=top_k,
            corpus_scope=corpus_scope,
            when=when,
        )
        return matches

    return retrieve


def make_shared_generator(
    *,
    corpus_scope: str = "utt_corpus",
    generation_approval_path: Path | None = None,
    benchmark_rows: Sequence[Mapping[str, Any]] | None = None,
    split: str | None = None,
    runtime_binding: Mapping[str, Any] | None = None,
    freeze_approval_path: Path | None = None,
    provider: OpenAICompatibleProvider | None = None,
) -> Callable[[str, Sequence[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any]]:
    """Return an answer callback bound to the application's generation pipeline.

    The default is retrieval-only.  To evaluate Gemini, this function itself
    loads and validates the owner-approved file against the exact dataset,
    split, runtime binding and (for Test) freeze.  A caller cannot enable the
    provider by passing a pre-built boolean or mapping.
    """
    generation_authorization = None
    if generation_approval_path is not None:
        if benchmark_rows is None or split is None or runtime_binding is None:
            raise BenchmarkProtocolError("BENCHMARK_GENERATION_VALIDATION_CONTEXT_REQUIRED")
        freeze_approval = (
            load_json_object(freeze_approval_path, "FINAL_FREEZE_APPROVAL")
            if freeze_approval_path is not None else None
        )
        generation_authorization = validate_generation_approval(
            load_generation_approval(generation_approval_path),
            rows=benchmark_rows,
            split=split,
            runtime_binding=runtime_binding,
            freeze_approval=freeze_approval,
        )
    llm_provider = provider

    def generate_answer(
        query: str,
        selected_candidates: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal llm_provider
        started = time.perf_counter()
        if not selected_candidates:
            return {
                "status": "insufficient_evidence",
                "answer": None,
                "claims": [],
                "citations": [],
                "latency_ms": (time.perf_counter() - started) * 1000.0,
            }

        provider_matches = _provider_matches(selected_candidates)
        chunks = [item["chunk"] for item in provider_matches]
        citations = [
            {
                "release_id": c.get("release_id", corpus_scope),
                "source": c.get("source"),
                "chunk_id": c.get("chunk_id"),
                "section": c.get("section"),
                "title": c.get("title"),
            }
            for c in chunks
        ]

        if generation_authorization is None:
            return {
                "status": "controlled_retrieval",
                "answer": None,
                "claims": [],
                "citations": citations,
                "reason": "BENCHMARK_GENERATION_APPROVAL_MISSING",
                "rag_mode": "beta_controlled",
                "latency_ms": (time.perf_counter() - started) * 1000.0,
            }

        # Approval was validated before the callback was returned.  Provider
        # creation is lazy, after that validation and only for a row with evidence.
        try:
            if llm_provider is None:
                llm_provider = OpenAICompatibleProvider()
            prompt_version = str(generation_authorization["prompt"]["version"])
            gen_res = llm_provider.generate(query, provider_matches, prompt_version=prompt_version)
            elapsed = (time.perf_counter() - started) * 1000.0
            return {
                "status": gen_res.get("status", "answered"),
                "answer": gen_res.get("answer"),
                "claims": gen_res.get("claims", []),
                "citations": gen_res.get("citations", citations),
                "usage": gen_res.get("usage", getattr(llm_provider, "last_usage", {})),
                "provider": generation_authorization["provider"],
                "prompt": generation_authorization["prompt"],
                "latency_ms": elapsed,
            }
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            return {
                "status": "provider_error",
                "error": type(exc).__name__,
                "answer": None,
                "claims": [],
                "citations": citations,
                "latency_ms": elapsed,
            }

    return generate_answer


def run_dev_comparison(
    *,
    dataset_path: Path,
    output_dir: Path,
    corpus_scope: str = "utt_corpus",
    methods: Sequence[str] = ("keyword", "dense", "hybrid"),
    answer_method: str | None = None,
    repo_root: Path | None = None,
    chunks_cache: list[dict] | None = None,
    runtime_binding: Mapping[str, Any] | None = None,
    generation_approval_path: Path | None = None,
) -> dict[str, Any]:
    """Run Dev split comparison across retrieval methods and save immutable report."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BenchmarkProtocolError("DEV_OUTPUT_DIRECTORY_NOT_EMPTY")
    output_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root or Path(__file__).resolve().parent.parent.parent

    rows = load_jsonl(dataset_path)
    protocol = validate_benchmark_protocol(rows)

    retriever = make_shared_retriever(corpus_scope=corpus_scope, chunks_cache=chunks_cache)
    binding = dict(runtime_binding) if runtime_binding is not None else {
        "repo_commit": get_git_commit(root),
        "corpus_scope": corpus_scope,
        "dataset_path": str(dataset_path),
        "dataset_canonical_sha256": protocol["dataset_canonical_sha256"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "provider": os.environ.get("RAG_LLM_PROVIDER", "none"),
        "model": os.environ.get("RAG_LLM_MODEL", "none"),
    }
    generator = make_shared_generator(
        corpus_scope=corpus_scope,
        generation_approval_path=generation_approval_path,
        benchmark_rows=rows,
        split="dev",
        runtime_binding=binding,
    )

    selected_answer_method = _answer_method_from_binding(binding, methods, answer_method)
    report = evaluate_dataset(
        rows,
        split="dev",
        retrieve=retriever,
        answer=generator,
        methods=methods,
        answer_method=selected_answer_method,
        runtime_binding=binding,
    )

    out_file = output_dir / f"dev_benchmark_report_{int(time.time())}.json"
    _write_exclusive_json(out_file, report)

    return {"report_file": str(out_file), "report": report}


def run_test_evaluation(
    *,
    dataset_path: Path,
    review_ledger_path: Path,
    approval_path: Path,
    release_receipt_path: Path,
    release_manifest_path: Path,
    output_dir: Path,
    runtime_binding: Mapping[str, Any],
    generation_approval_path: Path,
    corpus_scope: str = "utt_corpus",
    methods: Sequence[str] = ("keyword", "dense", "hybrid"),
    answer_method: str | None = None,
    chunks_cache: list[dict] | None = None,
) -> dict[str, Any]:
    """Run one-shot final test evaluation under strict freeze approval gates."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Preflight check: must pass all freeze gates, must not contain existing checkpoint
    preflight = prepare_final_run(
        dataset_path=dataset_path,
        review_ledger_path=review_ledger_path,
        approval_path=approval_path,
        release_receipt_path=release_receipt_path,
        release_manifest_path=release_manifest_path,
        output_dir=output_dir,
        runtime_binding=runtime_binding,
    )

    rows = load_jsonl(dataset_path)

    # 2. Validate the separate external-generation approval before provider
    # construction, then setup callbacks shared with the application retriever.
    retriever = make_shared_retriever(corpus_scope=corpus_scope, chunks_cache=chunks_cache)
    generator = make_shared_generator(
        corpus_scope=corpus_scope,
        generation_approval_path=generation_approval_path,
        benchmark_rows=rows,
        split="test",
        runtime_binding=runtime_binding,
        freeze_approval_path=approval_path,
    )

    started_file = output_dir / "FINAL_STARTED.json"
    _write_exclusive_json(started_file, {
        "status": "FINAL_STARTED",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset_canonical_sha256": preflight["dataset_canonical_sha256"],
        "freeze_approval_canonical_sha256": preflight["freeze_approval_canonical_sha256"],
        "resume_allowed": False,
    })

    # 4. Evaluate held-out Test split
    selected_answer_method = _answer_method_from_binding(runtime_binding, methods, answer_method)
    report = evaluate_dataset(
        rows,
        split="test",
        retrieve=retriever,
        answer=generator,
        methods=methods,
        answer_method=selected_answer_method,
        runtime_binding=runtime_binding,
    )

    # 5. Persist preflight receipt and final report immutably
    preflight_file = output_dir / "preflight_receipt.json"
    _write_exclusive_json(preflight_file, preflight)
    report_file = output_dir / "final_benchmark_report.json"
    _write_exclusive_json(report_file, report)
    completed_file = output_dir / "FINAL_COMPLETED.json"
    _write_exclusive_json(completed_file, {
        "status": "FINAL_COMPLETED",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "report_sha256": file_sha256(report_file),
        "preflight_sha256": file_sha256(preflight_file),
        "automatically_approved": False,
        "owner_review_required": True,
    })

    return {
        "status": "FINAL_EVALUATION_COMPLETED",
        "output_dir": str(output_dir),
        "preflight_file": str(preflight_file),
        "report_file": str(report_file),
        "completed_file": str(completed_file),
        "report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared RAG Benchmark V2 Adapter Runner")
    parser.add_argument("--dataset", required=True, help="Path to benchmark JSONL (120 items)")
    parser.add_argument("--split", choices=["dev", "test"], default="dev", help="Dataset split to evaluate")
    parser.add_argument("--output-dir", required=True, help="Directory to store immutable evaluation reports")
    parser.add_argument("--scope", default="utt_corpus", help="Corpus scope")
    parser.add_argument("--methods", nargs="+", default=["keyword", "dense", "hybrid"], help="Retrieval methods")
    parser.add_argument(
        "--answer-method",
        default=None,
        help="Optional explicit retriever for generation; defaults to immutable runtime binding",
    )
    parser.add_argument("--chunks-file", default=None, help="Optional JSON file with pre-loaded chunks")
    parser.add_argument("--approval", default=None, help="Path to freeze_approval.json (required for test split)")
    parser.add_argument("--review-ledger", default=None, help="Path to review_ledger.json")
    parser.add_argument("--release-receipt", default=None, help="Path to release_v2_receipt.json")
    parser.add_argument("--release-manifest", default=None, help="Path to release_v2_manifest.json")
    parser.add_argument("--runtime-binding", default=None, help="Path to runtime_binding.json")
    parser.add_argument("--generation-approval", default=None, help="Owner-approved isolated Gemini benchmark authorization")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)
    chunks_cache = None
    if args.chunks_file:
        cf = Path(args.chunks_file)
        raw = json.loads(cf.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            # Flatten if grouped by group_id
            chunks_cache = []
            for item in raw.values():
                if isinstance(item, list):
                    chunks_cache.extend(item)
        elif isinstance(raw, list):
            chunks_cache = raw

    if args.split == "dev":
        runtime_binding = load_json_object(args.runtime_binding, "RUNTIME_BINDING") if args.runtime_binding else None
        if args.generation_approval and runtime_binding is None:
            raise ValueError("--runtime-binding is required with --generation-approval.")
        res = run_dev_comparison(
            dataset_path=dataset_path,
            output_dir=output_dir,
            corpus_scope=args.scope,
            methods=args.methods,
            answer_method=args.answer_method,
            chunks_cache=chunks_cache,
            runtime_binding=runtime_binding,
            generation_approval_path=Path(args.generation_approval) if args.generation_approval else None,
        )
        print(f"Dev comparison complete. Saved report to: {res['report_file']}")
        print(f"Recommended method: {res['report'].get('dev_selection')}")
    else:
        if not args.approval:
            raise ValueError("--approval is required for test split execution.")
        if not args.generation_approval:
            raise ValueError("--generation-approval is required for a real Test generation run.")
        approval_path = Path(args.approval)
        ledger_path = Path(args.review_ledger) if args.review_ledger else dataset_path.parent / "review_ledger.json"
        receipt_path = Path(args.release_receipt) if args.release_receipt else Path("artifacts/corpus/release_v2_receipt.json")
        manifest_path = Path(args.release_manifest) if args.release_manifest else Path("artifacts/corpus/release_v2_manifest.json")
        if not args.runtime_binding:
            raise ValueError("--runtime-binding is required for test split execution.")
        runtime_binding = load_json_object(args.runtime_binding, "RUNTIME_BINDING")

        res = run_test_evaluation(
            dataset_path=dataset_path,
            review_ledger_path=ledger_path,
            approval_path=approval_path,
            release_receipt_path=receipt_path,
            release_manifest_path=manifest_path,
            output_dir=output_dir,
            runtime_binding=runtime_binding,
            generation_approval_path=Path(args.generation_approval),
            corpus_scope=args.scope,
            methods=args.methods,
            answer_method=args.answer_method,
            chunks_cache=chunks_cache,
        )
        print(f"Test split evaluation completed. Saved final report to: {res['report_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
