# Review benchmark RAG DEMO-1

`questions_benchmark_draft.jsonl` contains 120 **unreviewed** candidates: 60 dev and 60 test. Each split has 40 answerable questions, 10 insufficient-evidence questions, and 10 scope/version questions.

Before any metrics are reported, the owner must copy the file to `WORK/rag/questions_reviewed.jsonl`, then review every row:

1. Read `chunks.jsonl` generated from the current corpus. A changed corpus/chunker means regenerate the draft and review again.
2. For an `answerable` row, verify that `reference_claims`, `gold_evidence`, and `gold_chunk_ids` identify evidence that supports the requested claim. Correct them if needed.
3. For `insufficient_evidence`, confirm the DEMO corpus genuinely cannot answer it. For `scope_or_version`, confirm the configured scope/as-of must exclude it.
4. Set `reviewed` to `true` only for rows you have checked. Preserve `review_notes` with a short reason if you change gold evidence.
5. Do not edit test questions after dev metrics are inspected. Before test, generate and approve the final-RAG approval file, which binds both config and question-file hashes.

This is a single-reviewer benchmark unless a second reviewer is actually recorded. It measures retrieval only; without an LLM provider, answer correctness, citation-support precision, token usage, and cost remain null/not evaluated.
