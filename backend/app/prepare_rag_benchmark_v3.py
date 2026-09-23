"""Prepare an unreviewed RAG Benchmark V3 candidate without reopening V2 Test.

This command never signs or runs a benchmark.  It rejects question, group,
source, gold-chunk and evidence-span overlap with an earlier benchmark and
resets every owner-review field before writing a new immutable review batch.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from app.rag_benchmark_v2 import CATEGORIES, EXPECTED_COMPOSITION, PROTOCOL_VERSION, QUESTION_FIELDS, canonical_sha256, load_jsonl


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _span_keys(row: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for span in row.get("evidence_spans", []):
        if isinstance(span, Mapping):
            result.add(str(span.get("chunk_id") or span.get("text_sha256") or span.get("span_sha256") or canonical_sha256(span)))
    return result


def _collect(rows: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    material = list(rows)
    return {
        "question": {_norm(str(row.get("question") or "")) for row in material},
        "group": {str(row.get("group_id") or "") for row in material},
        "source": {str(row.get("source_document_id") or "") for row in material},
        "gold": {str(value) for row in material for value in row.get("gold_chunk_ids", [])},
        "span": {value for row in material for value in _span_keys(row)},
    }


def prepare(candidate_rows: list[dict[str, Any]], prior_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(candidate_rows) != 120:
        raise ValueError(f"V3_COUNT_MUST_BE_120_GOT_{len(candidate_rows)}")
    ids: set[str] = set()
    by_split: dict[str, list[dict[str, Any]]] = {"dev": [], "test": []}
    clean: list[dict[str, Any]] = []
    for row in candidate_rows:
        missing = [name for name in QUESTION_FIELDS if name not in row]
        if missing:
            raise ValueError("V3_MISSING_FIELDS:" + ",".join(missing))
        qid = str(row["question_id"])
        if not re.fullmatch(r"V3_[A-Za-z0-9_.-]+", qid) or qid in ids:
            raise ValueError(f"V3_QUESTION_ID_INVALID:{qid}")
        ids.add(qid)
        split, category = row.get("split"), row.get("benchmark_category")
        if split not in by_split or category not in CATEGORIES:
            raise ValueError(f"V3_SPLIT_OR_CATEGORY_INVALID:{qid}")
        prepared = dict(row)
        prepared.update({"reviewed": False, "reviewer": None, "reviewed_at": None})
        clean.append(prepared)
        by_split[split].append(prepared)
    for split, rows in by_split.items():
        if len(rows) != 60 or Counter(row["benchmark_category"] for row in rows) != Counter(EXPECTED_COMPOSITION):
            raise ValueError(f"V3_{split.upper()}_COMPOSITION_INVALID")

    prior, current = _collect(prior_rows), _collect(clean)
    # Reusing an official source document is expected: V3 evaluates the same
    # corpus.  Reusing a question, clause/group, gold chunk or evidence span is
    # not, because it would carry the opened V2 Test labels into a new final.
    for label in ("question", "group", "gold", "span"):
        overlap = sorted((prior[label] & current[label]) - {""})
        if overlap:
            raise ValueError(f"V3_PRIOR_{label.upper()}_OVERLAP:{overlap[0]}")
    dev, test = _collect(by_split["dev"]), _collect(by_split["test"])
    for label in ("question", "group", "source", "gold", "span"):
        overlap = sorted((dev[label] & test[label]) - {""})
        if overlap:
            raise ValueError(f"V3_CROSS_SPLIT_{label.upper()}_LEAKAGE:{overlap[0]}")

    ledger = {
        "protocol": PROTOCOL_VERSION,
        "approved": False,
        "owner": "",
        "reviewed_at": "",
        "dataset_canonical_sha256": "SET_AFTER_ALL_120_ROWS_ARE_OWNER_REVIEWED",
        "split_canonical_sha256": {
            "dev": "SET_AFTER_ALL_120_ROWS_ARE_OWNER_REVIEWED",
            "test": "SET_AFTER_ALL_120_ROWS_ARE_OWNER_REVIEWED",
        },
        "entries": [{"question_id": row["question_id"], "reviewed": False, "reviewer": None, "reviewed_at": None} for row in clean],
    }
    return clean, ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--prior-v2", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("V3_OUTPUT_DIRECTORY_NOT_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    rows, ledger = prepare(load_jsonl(args.candidate), load_jsonl(args.prior_v2))
    with (output / "questions_v3_owner_review.jsonl").open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    with (output / "review_ledger.template.json").open("x", encoding="utf-8") as stream:
        json.dump(ledger, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": "OWNER_REVIEW_REQUIRED", "question_count": len(rows), "output_dir": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
