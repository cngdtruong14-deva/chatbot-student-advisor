"""Synthetic OULAD-shaped fixtures ONLY. Not research training/evaluation evidence."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from ml.scripts.common import load,save,sha,read_jsonl
from ml.scripts.oulad import audit,features_and_splits
from ml.scripts.train import train_and_select,probability
from ml.scripts.package import export_bundle,final_evaluate,explanation

ROOT=Path(__file__).resolve().parents[2]


class ExperimentFixtureTests(unittest.TestCase):
    def create_raw(self,raw):
        raw.mkdir()
        info=[];registrations=[];vle=[];submissions=[]
        for i in range(240):
            uid=str(10000+i);label=i%2
            base={'id_student':uid,'code_module':'AAA','code_presentation':'2014J'}
            info.append({**base,'final_result':'Fail' if label else 'Pass','num_of_prev_attempts':label,'studied_credits':60})
            registrations.append({**base,'date_registration':-1,'date_unregistration':None})
            vle.append({**base,'id_site':'1','date':28,'sum_click':2 if label else 100})
            vle.append({**base,'id_site':'1','date':29,'sum_click':9000})
            submissions.append({'id_student':uid,'id_assessment':'1','date_submitted':20,'is_banked':0,'score':0 if label else 100})
        pd.DataFrame(info).to_csv(raw/'studentInfo.csv',index=False)
        pd.DataFrame(registrations).to_csv(raw/'studentRegistration.csv',index=False)
        pd.DataFrame(vle).to_csv(raw/'studentVle.csv',index=False)
        pd.DataFrame(submissions).to_csv(raw/'studentAssessment.csv',index=False)
        pd.DataFrame([{'id_assessment':'1','code_module':'AAA','code_presentation':'2014J','assessment_type':'TMA'}]).to_csv(raw/'assessments.csv',index=False)
        pd.DataFrame([{'code_module':'AAA','code_presentation':'2014J','module_presentation_length':200}]).to_csv(raw/'courses.csv',index=False)
        pd.DataFrame([{'id_site':'1'}]).to_csv(raw/'vle.csv',index=False)

    def test_synthetic_workflow_and_final_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'raw';self.create_raw(raw)
            config=load(ROOT/'ml/configs/experiment.json')
            # Synthetic provenance is valid only inside this discarded unit fixture,
            # never evidence for a real exported artifact.
            config.update(sample_students=0,source_commit='f'*40,source_commit_approved=True,
                          source_provenance={'source_kind':'clean_git_commit_source_archive','source_commit':'f'*40})
            report=audit(raw,root/'audit',config)
            self.assertEqual(report['eligible_rows'],240)
            with self.assertRaises(FileNotFoundError):
                features_and_splits(raw,root/'processed',root/'audit',root/'missing.json',config,ROOT/'contracts/oulad_features_v1.schema.json')
            approval=load(root/'audit/approval.template.json')
            approval.update(approved=True,owner='synthetic-unit-test',source_completeness_verified=True)
            save(root/'approval.json',approval)
            features_and_splits(raw,root/'processed',root/'audit',root/'approval.json',config,ROOT/'contracts/oulad_features_v1.schema.json')
            data={s:read_jsonl(root/f'processed/{s}.jsonl') for s in ['train','dev','test']}
            self.assertFalse({r['group_id'] for r in data['train']}&{r['group_id'] for r in data['test']})
            self.assertTrue(all(r['record']['features']['vle_clicks_0_28'] in [2,100] for rs in data.values() for r in rs))
            selection=train_and_select(root/'processed',root/'run',config)
            self.assertEqual(selection['selected']['model'],'logistic_regression')
            self.assertIsNone(selection['test_metrics'])
            self.assertEqual(selection['selected']['metrics']['average_precision'],1.0)
            manifest=export_bundle(root/'run',root/'processed',root/'candidate',ROOT/'contracts','synthetic-test-only')
            self.assertEqual(manifest['validation_level'],'dev_only')
            self.assertGreaterEqual(len(read_jsonl(root/'candidate/smoke_inputs.jsonl')),10)
            with self.assertRaises(ValueError):
                export_bundle(root/'run',root/'processed',root/'candidate',ROOT/'contracts','synthetic-test-only')
            save(root/'freeze.json',{'approved':True,'owner':'unit-test',
                 'selected_run_sha256':sha(root/'run/selected_run.json'),
                 'selected_model_sha256':selection['selected']['sha256']})
            result=final_evaluate(root/'run',root/'processed',root/'freeze.json')
            self.assertEqual(result['average_precision'],1.0)
            self.assertEqual(result['selected_model_sha256'],selection['selected']['sha256'])
            with self.assertRaises(FileExistsError):
                final_evaluate(root/'run',root/'processed',root/'freeze.json')

    def test_final_gate_rejects_mismatched_model_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=root/'raw';self.create_raw(raw)
            config=load(ROOT/'ml/configs/experiment.json')
            config.update(sample_students=0,source_commit='e'*40,source_commit_approved=True,
                          source_provenance={'source_kind':'clean_git_commit_source_archive','source_commit':'e'*40})
            audit(raw,root/'audit',config)
            approval=load(root/'audit/approval.template.json')
            approval.update(approved=True,owner='synthetic-unit-test',source_completeness_verified=True)
            save(root/'approval.json',approval)
            features_and_splits(raw,root/'processed',root/'audit',root/'approval.json',config,ROOT/'contracts/oulad_features_v1.schema.json')
            selection=train_and_select(root/'processed',root/'run',config)
            save(root/'freeze.json',{'approved':True,'owner':'unit-test',
                 'selected_run_sha256':sha(root/'run/selected_run.json'),'selected_model_sha256':'0'*64})
            with self.assertRaisesRegex(ValueError,'FINAL_FREEZE_REQUIRED'):
                final_evaluate(root/'run',root/'processed',root/'freeze.json')
            self.assertFalse((root/'run'/'FINAL_TEST_STARTED.json').exists())

    def test_class_order(self):
        import numpy as np
        class ReversedClasses:
            classes_=np.asarray([1,0])
            def predict_proba(self,X):
                return np.asarray([[.9,.1]])
        self.assertAlmostEqual(probability(ReversedClasses(),[[0]])[0],.9)

    def test_rf_explanation_additivity_on_synthetic_fixture(self):
        import numpy as np
        from sklearn.pipeline import Pipeline
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
        from sklearn.ensemble import RandomForestClassifier
        from advisor_core.ml_boundary import FEATURE_ORDER
        X=pd.DataFrame(np.random.default_rng(42).normal(size=(40,6)),columns=list(FEATURE_ORDER))
        y=(X.iloc[:,0]>0).astype(int)
        model=Pipeline([('imputer',SimpleImputer(keep_empty_features=True)),('scaler',StandardScaler()),
                        ('classifier',RandomForestClassifier(n_estimators=5,random_state=42))]).fit(X,y)
        result=explanation(model,X.iloc[:10],'random_forest')
        self.assertEqual(result['method'],'shap_tree')
        self.assertLessEqual(result['max_error'],1e-5)
