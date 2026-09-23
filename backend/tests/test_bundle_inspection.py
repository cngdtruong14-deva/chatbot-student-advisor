import hashlib
import json
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from advisor_core.ml_boundary import FEATURE_ORDER, verify_bundle_files


class BundleInspectionTests(unittest.TestCase):
    def fixture(self, root):
        files = ['pipeline.joblib','feature_schema.json','metrics.json','model_card.md','requirements-lock.txt',
                 'splits_manifest.json','smoke_inputs.jsonl','smoke_expected.jsonl','explanation_config.json']
        content = b'NONEXECUTABLE SYNTHETIC INSPECTION FIXTURE'
        manifest = {"contract_version":"1.0.0","model_id":"fixture-model","model_version":"test-only",
          "domain_id":"oulad","target_id":"non_completion_at_end","target_description":"Synthetic fixture, not a trained or validated research model",
          "positive_label":1,"cutoff_day":28,"feature_schema_id":"oulad_risk_day28","feature_schema_version":"1.0.0",
          "feature_order":list(FEATURE_ORDER),"advisor_core_version":version('sic-advisor-core'),"source_commit":"0"*40,
          "trained_at":"2026-09-06T00:00:00Z","validation_level":"dev_only",
          "environment":{"python_version":"3.12.0","platform":"fixture","packages":{k:"fixture" for k in ['scikit-learn','numpy','pandas','scipy','joblib']}},
          "dataset_sha256":"0"*64,"split_sha256":"0"*64,"calibration_method":"none","alert_threshold":0.5,
          "parity_absolute_tolerance":0.000001,"explanation":{"method":"linear_contribution","explained_output":"log_odds",
          "class_label":1,"config_file":"explanation_config.json","background_file":None,"base_model_file":None,"calibration_note":"fixture"},
          "files":{name:{"sha256":hashlib.sha256(content).hexdigest(),"size_bytes":len(content)} for name in files}}
        for name in files:
            (root/name).write_bytes(content)
        (root/'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_inspection_does_not_load_fake_pickle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = verify_bundle_files(root, '/contracts/model_manifest.schema.json')
            self.assertFalse(result['model_ready'])
            self.assertEqual(result['status'], 'files_verified_only')

    def test_changed_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            p = root/'pipeline.joblib'
            p.write_bytes(b'X'*p.stat().st_size)
            with self.assertRaisesRegex(ValueError, 'HASH'):
                verify_bundle_files(root, '/contracts/model_manifest.schema.json')

    def test_traversal_and_order(self):
        for variant in ['traversal','order','core']:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.fixture(root)
                if variant=='traversal':
                    manifest['files']['sub/../../outside'] = manifest['files']['metrics.json']
                elif variant=='order':
                    manifest['feature_order'].reverse()
                else:
                    manifest['advisor_core_version']='wrong-version'
                (root/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_bundle_files(root, '/contracts/model_manifest.schema.json')

    def test_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root/'link').symlink_to(root/'metrics.json')
            manifest=json.loads((root/'manifest.json').read_text())
            manifest['files']['link']=manifest['files']['metrics.json']
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'UNSAFE'):
                verify_bundle_files(root, '/contracts/model_manifest.schema.json')
