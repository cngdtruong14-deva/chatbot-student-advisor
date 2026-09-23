# ML/RAG implementation status — 2026-09-06

## Decisions

Owner selected DEMO-1 corpus, retrieval/citations without LLM API. Future API adapter is a separate extension;
the current implementation does not send requests or secrets to an LLM provider.
OULAD is the primary research dataset compatible with contract1.0.0. Kaggle URL contents/schema/license
could not be verified from the provided page; it was not substituted into OULAD features.

## Implemented

- Seven clean Colab notebooks00–06, explicit inputs and approval gates.
- Audit and streaming OULAD CSV adapter; shared feature builder, student-disjoint splits, train/dev/test files and hashes.
- Dummy/LR/RF pipelines, dev AP selection, dev F1 threshold, required metrics and reliability plot.
- LR contribution/RF SHAP, immutable export manifest, smoke IO/reload parity, separate final test gate/marker.
- Shared paragraph chunker, keyword baseline, Chroma PersistentClient + pinned multilingual E5 dense adapter,
  scope/as-of filters before retrieval, versioned citation excerpts, generation-unavailable adapter.
- Approved-policy-derived DEMO corpus and a 120-question **unreviewed** benchmark draft: 60 dev/60 test; each split has 40 answerable, 10 insufficient-evidence and 10 scope/version cases. Gold evidence is mapped to the current chunks but requires owner review before metrics.
- Colab runbook and source-only packaging script. Package0.3.0; contract1.0.0 unchanged.

## Not claimed / external gates

Local verification: clean notebook JSON/code parsing, keyword scope/as-of/citation behavior,
approval hash binding, synthetic end-to-end audit/split/train-dev/export/final-once test, positive-class mapping,
RF SHAP additivity, full benchmark composition/approval template and dependency `pip check`: **10 tests PASS** on isolated Python3.12 Windows.
`ml/test_ml_isolation.py`: PASS core0.3.0 / contract1.0.0, no runtime credential names.
Synthetic fixture metrics are test assertions only, not OULAD performance.

- Real OULAD audit/training/export executed on Colab Python3.13.15 from commit `e388e7744e85c7a44a51c0954b7d2c92decf68fb`. `final-002` is an immutable OULAD research bundle: test AP0.5892, ROC-AUC0.6385, recall0.8028, precision0.4750, F1 0.5969, Brier0.2310 on329 test cases. It is not a model for NTTU/demo student profiles.
- Chroma/model download/dense index smoke executed for the DEMO corpus. Index construction is not a retrieval benchmark.
- Human-reviewed60dev/60test benchmark and RAG answer-quality evaluation remain outstanding. Generation metrics are null because no LLM provider was selected.
- Training/export source used a clean Git-commit archive and records the approved commit above; no working-tree snapshot was used for `final-002`.
- Backend currently runs the earlier package/image. No runtime migration, API model activation or Chroma deployment was performed in this Colab task.
  Integrate returned bundles/chunks only after backend trust/environment/parity checks, with matching core0.3.0.

## Security / scope

No DB secrets, .env, student profiles or model binaries are included in the source ZIP. No Docker volume removal,
Git reset, push/merge, paid provider setup or fine-tuning was performed. Existing backend/frontend changes were preserved.

STATUS: PARTIAL — ML research bundle is verified; RAG requires owner review of gold evidence and execution of dev/final retrieval benchmark.
