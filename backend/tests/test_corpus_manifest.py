import json
import tempfile
import unittest
from pathlib import Path
from app.corpus_manifest import canonical_hash, file_hash, load_reviewed_manifest, text_hash, validate_source
from app.knowledge import _scope_matches


class CorpusManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.raw = self.root/'raw'; self.raw.mkdir(); (self.raw/'a.pdf').write_bytes(b'raw')
        self.item = {'source_id':'a','filename':'a.pdf','title':'A','source':'https://utt.test/a',
            'raw_sha256':file_hash(self.raw/'a.pdf'),'text_sha256':text_hash('text'),
            'major':'all','cohort':'K75+','is_effective_date_verified':False,
            'review_state':'reviewed','reviewer':'owner','title_verified':True,
            'source_verified':True,'page_coverage_verified':True,'table_coverage_verified':True}

    def tearDown(self): self.tmp.cleanup()

    def write(self, item=None):
        payload={'manifest_version':'2.0.0','status':'owner_reviewed','owner':'owner',
                 'reviewed_at':'2026-09-20T00:00:00Z','documents':[item or self.item]}
        payload['manifest_sha256']=canonical_hash(payload)
        path=self.root/'manifest.json'; path.write_text(json.dumps(payload),encoding='utf-8'); return path

    def test_review_hash_and_independent_source_hashes(self):
        _, lookup=load_reviewed_manifest(self.write(),expected_count=1)
        self.assertEqual(validate_source(lookup['a'],{'content':'text'},self.raw),
                         (self.item['raw_sha256'],self.item['text_sha256']))

    def test_review_cannot_be_inferred(self):
        item=dict(self.item,reviewer=None,page_coverage_verified=False)
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_REVIEWED|COVERAGE'):
            load_reviewed_manifest(self.write(item),expected_count=1)

    def test_hash_mismatch_fails_closed(self):
        item=dict(self.item,raw_sha256='0'*64)
        _, lookup=load_reviewed_manifest(self.write(item),expected_count=1)
        with self.assertRaisesRegex(ValueError,'RAW_HASH_MISMATCH'):
            validate_source(lookup['a'],{'content':'text'},self.raw)

    def test_scope_matching(self):
        self.assertTrue(_scope_matches('all','CNTT'))
        self.assertTrue(_scope_matches('CNTT,HTTT','cntt'))
        self.assertFalse(_scope_matches('CNTT','Kỹ thuật xây dựng'))
        self.assertTrue(_scope_matches('K75+','K76',cohort_mode=True))
        self.assertFalse(_scope_matches('K75+','K74',cohort_mode=True))
