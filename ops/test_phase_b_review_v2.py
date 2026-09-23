import copy
import json
import tempfile
import unittest
from pathlib import Path
from phase_b_review_v2 import evaluate, metrics


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.packet = {"packet_version": 2, "source_manifest_sha256": "a", "page_manifest_sha256": "b", "records": [
            {"id": "B01-01", "source_id": "source", "page_index": 1, "raw_sha256": "c", "text_sha256": "d", "ocr_text": "abc", "decision": "pending", "critical_verified": False}]}
        self.reply = copy.deepcopy(self.packet)
        self.reply.update(reviewer="Owner", reviewed_at="2026-09-18")

    def run_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/"packet.json", Path(tmp)/"reply.json"
            a.write_text(json.dumps(self.packet), encoding="utf-8")
            b.write_text(json.dumps(self.reply), encoding="utf-8")
            return evaluate(a, b)

    def test_known_metric(self):
        self.assertAlmostEqual(metrics("abc", "axc")["cer"], 1/3)

    def test_empty_gold_rejected(self):
        with self.assertRaises(ValueError): metrics("", "abc")

    def test_pending_has_no_metric(self):
        self.assertIsNone(self.run_eval()["results"][0]["metrics"])

    def test_stale_manifest_rejected(self):
        self.reply["page_manifest_sha256"] = "changed"
        with self.assertRaises(ValueError): self.run_eval()

    def test_tampered_ocr_rejected(self):
        self.reply["records"][0]["ocr_text"] = "tampered"
        with self.assertRaises(ValueError): self.run_eval()

    def test_missing_reviewer_rejected(self):
        self.reply["reviewer"] = ""
        with self.assertRaises(ValueError): self.run_eval()

    def test_accept_requires_critical_review(self):
        self.reply["records"][0]["decision"] = "accepted"
        with self.assertRaises(ValueError): self.run_eval()

    def test_corrected_requires_gold(self):
        self.reply["records"][0].update(decision="corrected", critical_verified=True)
        with self.assertRaises(ValueError): self.run_eval()

    def test_accepted_explicitly(self):
        self.reply["records"][0].update(decision="accepted", critical_verified=True)
        result = self.run_eval()
        self.assertEqual(result["results"][0]["metrics"]["cer"], 0)
        self.assertEqual(result["status"], "BATCH_ONLY_NOT_PHASE_ACCEPTANCE")


if __name__ == "__main__": unittest.main()
