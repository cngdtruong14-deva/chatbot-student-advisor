"""Integration tests for corpus release lifecycle, receipts and atomic rollback."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.store import engine, one, rows, run
from app.corpus_release import build_staging_release, activate_release, rollback_release, get_active_release
from app.corpus_manifest import canonical_hash, file_hash, text_hash


from contextlib import contextmanager


class LifecycleFixtureEmbedder:
    """Offline vectors for storage/lifecycle only, never retrieval evaluation."""

    def encode(self, texts, normalize_embeddings=True):
        import numpy as np
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        vectors[:, 0] = 1.0
        return vectors


@unittest.skipUnless(os.environ.get("ADVISOR_DOCUMENT_DB_TEST") == "1", "explicit database test required")
class CorpusReleaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.conn = engine().connect()
        self.outer = self.conn.begin()
        self.uid = uuid4()
        run(
            self.conn,
            "INSERT INTO app.users(id, email, password_hash, role) VALUES(:id, :email, 'test-pw', 'admin')",
            id=self.uid,
            email=f"{self.uid}@test.invalid",
        )
        @contextmanager
        def isolated():
            with self.conn.begin_nested(): yield self.conn
        self.patches = [
            patch("app.corpus_release.transaction", isolated),
            patch("app.knowledge.transaction", isolated),
        ]
        for p in self.patches:
            p.start()

        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.extracted_dir = Path(self._tmp.name)
        d1 = {"filename": "Quy che dao tao.pdf", "format": "pdf", "content": "## Trang 1\nĐiều 1. Phạm vi.\n1. Quy định đào tạo.\n* Lưu ý: Ngoại lệ."}
        d2 = {"filename": "Don xin hoc lai.docx", "format": "docx", "content": "ĐƠN XIN HỌC LẠI\nKính gửi phòng Đào tạo."}
        (self.extracted_dir / "doc1.json").write_text(json.dumps(d1), encoding="utf-8")
        (self.extracted_dir / "doc2.json").write_text(json.dumps(d2), encoding="utf-8")
        self.raw_dir = self.extracted_dir / 'raw'; self.raw_dir.mkdir()
        (self.raw_dir / d1['filename']).write_bytes(b'raw-pdf-fixture')
        (self.raw_dir / d2['filename']).write_bytes(b'raw-docx-fixture')
        documents = []
        for sid, doc in [('doc1', d1), ('doc2', d2)]:
            documents.append({'source_id':sid, 'filename':doc['filename'], 'title':Path(doc['filename']).stem,
                'source':'https://example.test/'+sid, 'format':doc['format'], 'major':'all', 'cohort':'all',
                'effective_from':None, 'effective_until':None, 'is_effective_date_verified':False,
                'raw_sha256':file_hash(self.raw_dir/doc['filename']), 'text_sha256':text_hash(doc['content']),
                'review_state':'reviewed', 'reviewer':'owner-test', 'title_verified':True,
                'source_verified':True, 'page_coverage_verified':True, 'table_coverage_verified':True})
        manifest = {'manifest_version':'2.0.0','status':'owner_reviewed','owner':'owner-test',
                    'reviewed_at':'2026-09-20T00:00:00Z','documents':documents}
        manifest['manifest_sha256'] = canonical_hash(manifest)
        self.manifest = self.extracted_dir/'reviewed.json'
        self.manifest.write_text(json.dumps(manifest), encoding='utf-8')
        exclusions = {'status':'temporarily_excluded','owner':'owner-test','source_ids':['excluded-source']}
        self.exclusions = self.extracted_dir/'exclusions.json'
        self.exclusions.write_text(json.dumps(exclusions), encoding='utf-8')

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()
        self.outer.rollback()
        self.conn.close()

    def test_build_staging_release_and_receipt_verification(self):
        import chromadb
        from chromadb.config import Settings

        # Real persistent storage owned by the current non-root test user.
        # Never use /vectorstore, live mounts, network downloads or E5 cache.
        client = chromadb.PersistentClient(
            path=str(self.extracted_dir / "chroma"),
            settings=Settings(anonymized_telemetry=False),
        )
        release_id = f"UTT-CORPUS-TEST-{uuid4().hex[:8]}"
        res = build_staging_release(
            release_id=release_id,
            corpus_scope="utt_corpus",
            extracted_dir=self.extracted_dir,
            owner_exclusions_file=self.exclusions,
            metadata_manifest_file=self.manifest,
            raw_dir=self.raw_dir,
            expected_document_count=2,
            admin_user_id=self.uid,
            client_instance=client,
            embedder_instance=LifecycleFixtureEmbedder(),
        )
        receipt = res["receipt"]
        self.assertEqual(receipt["status"], "staging")
        self.assertEqual(receipt["embedding_dimension"], 384)
        self.assertTrue(receipt["checks"]["chunk_count_matched"])
        self.assertTrue(receipt["checks"]["hashes_verified"])
        self.assertTrue(receipt["checks"]["embedding_dimension_verified"])
        self.assertGreater(receipt["chunk_count"], 0)
        self.assertTrue((self.extracted_dir / "chroma" / "chroma.sqlite3").is_file())

        # Check DB record
        rel_row = one(self.conn, "SELECT * FROM app.corpus_releases WHERE id=:id", id=release_id)
        self.assertIsNotNone(rel_row)
        self.assertEqual(rel_row["status"], "staging")

        # Activate release
        act_res = activate_release(release_id, admin_user_id=self.uid, client_instance=client)
        self.assertEqual(act_res["status"], "active")

        active = get_active_release("utt_corpus")
        self.assertIsNotNone(active)
        self.assertEqual(active["id"], release_id)
        with self.assertRaisesRegex(ValueError, 'IMMUTABLE_RELEASE_ID_ALREADY_EXISTS'):
            build_staging_release(release_id=release_id, corpus_scope='utt_corpus',
                extracted_dir=self.extracted_dir, owner_exclusions_file=self.exclusions,
                metadata_manifest_file=self.manifest, raw_dir=self.raw_dir,
                expected_document_count=2, admin_user_id=self.uid,
                client_instance=client, embedder_instance=LifecycleFixtureEmbedder())
        run(self.conn, "UPDATE app.corpus_releases SET status='retired' WHERE id=:id", id=release_id)
        run(self.conn, "UPDATE app.document_versions SET status='retired' WHERE release_id=:id", id=release_id)
        rolled = rollback_release(release_id, self.uid, client)
        self.assertTrue(rolled['rollback'])
        self.assertEqual(get_active_release('utt_corpus')['id'], release_id)

    def test_failed_activation_preserves_prior_release(self):
        # 1. Baseline active release
        base_id = f"BASE-REL-{uuid4().hex[:8]}"
        base_receipt = json.dumps({
            "status": "active",
            "checks": {
                "chunk_count_matched": True,
                "embedding_dimension_verified": True,
                "hashes_verified": True,
            },
        })
        run(
            self.conn,
            """INSERT INTO app.corpus_releases(
                id, corpus_scope, status, chunker_version, embedding_model, embedding_revision,
                embedding_dimension, collection_name, chunk_count, chunks_hash, source_manifest_hash,
                receipt, activated_at
            ) VALUES (
                :id, 'utt_corpus', 'active', 'v1', 'intfloat/multilingual-e5-small',
                '614241f622f53c4eeff9890bdc4f31cfecc418b3', 384, 'col-base', 10, 'hash-base', 'src-base',
                CAST(:receipt AS jsonb), now()
            )""",
            id=base_id,
            receipt=base_receipt,
        )

        # 2. Staging release with corrupted receipt (failure injection)
        corrupted_id = f"BROKEN-REL-{uuid4().hex[:8]}"
        broken_receipt = json.dumps({
            "status": "staging",
            "checks": {
                "chunk_count_matched": False,
                "embedding_dimension_verified": True,
                "hashes_verified": False,
            },
        })
        run(
            self.conn,
            """INSERT INTO app.corpus_releases(
                id, corpus_scope, status, chunker_version, embedding_model, embedding_revision,
                embedding_dimension, collection_name, chunk_count, chunks_hash, source_manifest_hash,
                receipt
            ) VALUES (
                :id, 'utt_corpus', 'staging', 'v1', 'intfloat/multilingual-e5-small',
                '614241f622f53c4eeff9890bdc4f31cfecc418b3', 384, 'col-broken', 10, 'hash-broken', 'src-broken',
                CAST(:receipt AS jsonb)
            )""",
            id=corrupted_id,
            receipt=broken_receipt,
        )

        # 3. Attempting to activate broken release must fail
        with self.assertRaisesRegex(ValueError, "INVALID_RELEASE_RECEIPT"):
            activate_release(corrupted_id, admin_user_id=self.uid, client_instance=object())

        # 4. Verify baseline release remains active and unchanged!
        current = get_active_release("utt_corpus")
        self.assertIsNotNone(current)
        self.assertEqual(current["id"], base_id)
        self.assertEqual(current["status"], "active")


if __name__ == "__main__":
    unittest.main()
