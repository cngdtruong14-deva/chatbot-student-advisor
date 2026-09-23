import unittest

from app.apply_effectivity_review import canonical_hash, validate_review
from app.prepare_effectivity_review import prepare
from app.rag_benchmark_v2 import V3_FREEZE_VERSION, V4_FREEZE_VERSION
from app.sign_stage7_approval import _hash, _validate_freeze, _validate_runtime
from app.rag_generation_approval import BenchmarkGenerationBlocked, _validate_final_freeze_binding


HASH = "a" * 64


class Stage7GovernanceTests(unittest.TestCase):
    def test_effectivity_template_never_infers_or_approves_dates(self):
        receipt = {
            "release_id": "release-v2",
            "source_manifest_hash": HASH,
            "receipt_sha256": "",
        }
        receipt["receipt_sha256"] = canonical_hash(receipt, omit=("receipt_sha256",))
        manifest = {
            "release_id": "release-v2",
            "document_count": 44,
            "source_manifest_hash": HASH,
            "source_set": [{"source_id": f"doc-{index}", "raw_sha256": HASH, "title": f"Doc {index}"} for index in range(44)],
        }
        value = prepare(manifest, receipt)
        self.assertFalse(value["approved"])
        self.assertTrue(all(item["effective_from"] == "OWNER_MUST_SET_YYYY-MM-DD" for item in value["documents"]))

    def test_effectivity_signed_hash_is_fail_closed(self):
        value = {
            "protocol": "utt_effectivity_review_v1",
            "approved": True,
            "owner": "admin@example.invalid",
            "reviewed_at": "2026-09-20T00:00:00Z",
            "release_id": "release-v2",
            "release_receipt_sha256": HASH,
            "documents": [{"source_id": f"doc-{index}", "raw_sha256": HASH, "effective_from": "2026-01-01", "effective_until": None} for index in range(44)],
        }
        value["approval_sha256"] = canonical_hash(value)
        self.assertEqual(len(validate_review(value)), 44)
        value["documents"][0]["effective_from"] = "2026-01-02"
        with self.assertRaisesRegex(ValueError, "EFFECTIVITY_APPROVAL_HASH_INVALID"):
            validate_review(value)

    def test_v3_freeze_requires_canonical_signature(self):
        approval = {
            "freeze_version": V3_FREEZE_VERSION,
            "final_split": "test",
            "dev_evidence": {"report_sha256": HASH},
            "approved": True,
            "owner": "Owner",
        }
        _validate_freeze(approval)
        approval["approval_sha256"] = _hash(approval)
        signed = approval["approval_sha256"]
        approval["owner"] = "Other"
        self.assertNotEqual(_hash(approval), signed)

    def test_v4_freeze_uses_distinct_version_and_signature(self):
        approval = {
            "freeze_version": V4_FREEZE_VERSION,
            "final_split": "test",
            "dev_evidence": {"report_sha256": HASH},
            "approved": True,
            "owner": "Owner",
        }
        _validate_freeze(approval)
        approval["approval_sha256"] = _hash(approval)
        signed = approval["approval_sha256"]
        approval["dev_evidence"]["report_sha256"] = "b" * 64
        self.assertNotEqual(_hash(approval), signed)

    def test_test_generation_binding_matches_only_the_test_split_hash(self):
        shared = {
            "release": {"release_id": "r"},
            "retriever": {"version": "v", "sha256": HASH},
            "prompt": {"version": "p", "sha256": HASH},
            "provider": {"provider": "gemini", "model": "m", "version": "v", "sha256": HASH},
            "source_provenance": {"git_commit": "b" * 40},
        }
        freeze = {
            **shared,
            "final_split": "test",
            "dataset": {"canonical_sha256": HASH, "split_canonical_sha256": {"dev": "b" * 64, "test": "c" * 64}},
        }
        generation = {
            **shared,
            "dataset": {"canonical_sha256": HASH, "split_canonical_sha256": "c" * 64},
        }
        _validate_final_freeze_binding(freeze, generation, "test")
        generation["dataset"]["split_canonical_sha256"] = "d" * 64
        with self.assertRaisesRegex(BenchmarkGenerationBlocked, "FREEZE_TEST_SPLIT_MISMATCH"):
            _validate_final_freeze_binding(freeze, generation, "test")

    def test_capstone_runtime_waiver_accepts_exactly_one_reviewed_safe_gap(self):
        rejected_id = "V4_TEST_A013"
        value = {
            "protocol": "rag_runtime_quality_v2",
            "benchmark": {"split": "test", "final_report_sha256": HASH},
            "quality_gates": {
                "hit_at_5": True, "mrr_at_5": True, "safe_abstention": True,
                "citation_precision": True, "answer_correctness": False,
                "scope_leakage_zero": True,
            },
            "semantic_review": {
                "entries": [
                    {"question_id": f"V4_TEST_A{index:03d}", "approved": index != 13}
                    for index in range(1, 61)
                ],
            },
            "capstone_waiver": {
                "protocol": "capstone_demo_quality_waiver_v1",
                "approved": False,
                "scope": "capstone_demo_only",
                "final_report_sha256": HASH,
                "observed_answer_correctness_proxy": 0.875,
                "minimum_accepted_answer_correctness_proxy": 0.875,
                "accepted_rejected_question_ids": [rejected_id],
                "risk_controls": {
                    "citations_required": True, "fail_closed": True,
                    "high_stakes_retrieval_only": True, "release_hash_bound": True,
                },
            },
        }
        _validate_runtime(value)
        value["capstone_waiver"]["risk_controls"]["fail_closed"] = False
        with self.assertRaisesRegex(ValueError, "SAFETY_CONTROLS_REQUIRED"):
            _validate_runtime(value)


if __name__ == "__main__":
    unittest.main()
