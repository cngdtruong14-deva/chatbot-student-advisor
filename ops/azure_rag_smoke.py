"""Read-only Azure staging smoke for approved UTT retrieval and Gemini generation."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/app")

from app.knowledge import search


def compact(result: dict) -> dict:
    matches = result.get("matches") or result.get("citations") or []
    return {
        "status": result.get("status"),
        "retrieval_status": result.get("retrieval_status"),
        "generation_status": result.get("generation_status"),
        "answer": result.get("answer") or result.get("message"),
        "source_count": len(matches),
        "corpus_scope": result.get("corpus_scope"),
        "retrieval_method": result.get("retrieval_method"),
    }


def main() -> None:
    grounded = search("Văn phòng Công đoàn UTT ở đâu?", corpus_scope="utt_corpus")
    print("GROUNDED=" + json.dumps(compact(grounded), ensure_ascii=False, default=str))
    if grounded.get("status") not in {"answered", "ok", "success"}:
        # Diagnostic keeps the key secret and emits only the adapter's stable
        # failure category for deployment troubleshooting.
        from app.knowledge import accessible_chunks, retrieve_candidates
        from app.llm_runtime import OpenAICompatibleProvider, config_from_env

        config = config_from_env()
        chunks = accessible_chunks(corpus_scope="utt_corpus")
        matches = retrieve_candidates(
            "Văn phòng Công đoàn UTT ở đâu?",
            chunks,
            method=os.environ.get("RAG_METHOD", "keyword"),
            top_k=5,
            corpus_scope="utt_corpus",
        )
        diagnostic = OpenAICompatibleProvider(config).generate(
            "Văn phòng Công đoàn UTT ở đâu?",
            matches,
            prompt_version=os.environ.get("RAG_LLM_PROMPT_VERSION"),
        )
        print(
            "PROVIDER_DIAGNOSTIC="
            + json.dumps(
                {
                    "configured": config.configured,
                    "model": config.model,
                    "status": diagnostic.get("status"),
                    "failure_reason": diagnostic.get("failure_reason"),
                    "usage": diagnostic.get("usage", {}),
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit("GROUNDED_QUERY_NOT_ANSWERED")
    if not (grounded.get("matches") or grounded.get("citations")):
        raise SystemExit("GROUNDED_QUERY_MISSING_CITATIONS")

    abstain = search(
        "UTT có căn cứ nào xác nhận sinh viên được du hành sao Hỏa miễn phí?",
        corpus_scope="utt_corpus",
    )
    print("ABSTAIN=" + json.dumps(compact(abstain), ensure_ascii=False, default=str))
    if abstain.get("status") not in {"insufficient_evidence", "abstained", "no_evidence"}:
        raise SystemExit("OUT_OF_CORPUS_QUERY_DID_NOT_ABSTAIN")


if __name__ == "__main__":
    main()
