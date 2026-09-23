"""Immutable export after trusted local training; source commit gate is mandatory."""
import json
import re
import shutil
from pathlib import Path
import joblib
import numpy as np
from jsonschema import Draft202012Validator, FormatChecker
from advisor_core.ml_boundary import FEATURE_ORDER, validate_features
from .common import load,save,sha,jsonl,read_jsonl,environment,require_approval
from .train import matrix,probability,metrics


def selected_model(run):
    run=Path(run); selection=load(run/'selected_run.json'); selected=selection['selected']
    path=run/selected['path']
    if not path.resolve().is_relative_to(run.resolve()) or path.is_symlink() or sha(path)!=selected['sha256']:
        raise ValueError('UNTRUSTED_OR_CHANGED_LOCAL_TRAINING_ARTIFACT')
    # Only run-owned artifacts produced by train.py; never accept arbitrary uploaded pickle.
    return selection,joblib.load(path)


def explanation(model,X,name):
    transformed=model[:-1].transform(X)
    clf=model.named_steps['classifier']
    if name=='logistic_regression':
        contributions=transformed*clf.coef_[0]
        base=float(clf.intercept_[0]); output=np.asarray(model.decision_function(X))
        method,scale='linear_contribution','log_odds'
    elif name=='random_forest':
        import shap
        explainer=shap.TreeExplainer(clf)
        values=explainer.shap_values(transformed)
        index=list(clf.classes_).index(1)
        contributions=np.asarray(values[index] if isinstance(values,list) else values[:,:,index])
        base=float(explainer.expected_value[index]); output=probability(model,X)
        method,scale='shap_tree','probability'
    else:
        raise ValueError('DUMMY_SELECTED: report baseline result; no deployable explanation in contract, do not substitute another model silently')
    error=float(np.max(np.abs(base+contributions.sum(axis=1)-output)))
    if error>1e-5:
        raise ValueError('EXPLANATION_ADDITIVITY_FAILED')
    return {'method':method,'explained_output':scale,'class_label':1,'base_value':base,
      'transformed_feature_order':list(FEATURE_ORDER),'additivity_tolerance':1e-5,'max_error':error,
      'calibration_note':'No fitted calibrator; contributions are associations, not causal effects',
      'smoke_contributions':contributions.tolist(),'smoke_output':output.tolist()}


def export_bundle(run,processed,destination,contracts,model_version,final_metrics=None):
    run,processed,destination,contracts=map(Path,[run,processed,destination,contracts])
    selection,model=selected_model(run)
    config=selection['config']; commit=config.get('source_commit')
    provenance=config.get('source_provenance',{})
    if (not config.get('source_commit_approved') or not isinstance(commit,str)
            or not re.fullmatch('[a-f0-9]{40}',commit) or commit=='0'*40
            or provenance.get('source_commit')!=commit
            or provenance.get('source_kind') not in {'clean_git_commit_source_archive','local_verified_synthetic_run'}):
        raise ValueError('PIN_APPROVED_SOURCE_COMMIT_BEFORE_EXPORT')
    if final_metrics is not None and (
            final_metrics.get('selected_run_sha256') != sha(run/'selected_run.json')
            or final_metrics.get('selected_model_sha256') != selection['selected']['sha256']):
        raise ValueError('FINAL_METRICS_NOT_BOUND_TO_CURRENT_FROZEN_MODEL')
    split=load(processed/'splits_manifest.json')
    if sha(processed/'splits_manifest.json')!=selection['splits_manifest_sha256'] or sha(processed/'dev.jsonl')!=split['files']['dev']:
        raise ValueError('SPLIT_CHANGED')
    dev=read_jsonl(processed/'dev.jsonl')[:20]
    if len(dev)<10:
        raise ValueError('TEN_SMOKE_CASES_REQUIRED')
    for r in dev:
        validate_features(r['record'],contracts/'oulad_features_v1.schema.json',allow_synthetic=config.get('data_origin')=='synthetic')
    X,_=matrix(dev);p=probability(model,X)
    explain=explanation(model,X,selection['selected']['model'])
    if destination.exists():
        raise ValueError('IMMUTABLE_BUNDLE_EXISTS')
    destination.mkdir(parents=True)
    joblib.dump(model,destination/'pipeline.joblib')
    reloaded=joblib.load(destination/'pipeline.joblib')
    if not np.allclose(p,probability(reloaded,X),atol=1e-6,rtol=0):
        raise ValueError('RELOAD_PARITY_FAILED')
    threshold=selection['selected']['metrics']['threshold']
    jsonl(destination/'smoke_inputs.jsonl',[r['record'] for r in dev])
    jsonl(destination/'smoke_expected.jsonl',[{'case_id':r['record']['case_id'],'risk_probability':float(v),'alert':bool(v>=threshold)} for r,v in zip(dev,p)])
    save(destination/'explanation_config.json',explain)
    save(destination/'metrics.json',{'validation_level':'final_test' if final_metrics else 'dev_only',
      'dev_metrics':selection['selected']['metrics'],'test_metrics':final_metrics,'comparison_dev':selection['comparison'],
      'beats_dummy_ap':selection['beats_dummy_ap'],'test_status':'evaluated' if final_metrics else 'not_evaluated'})
    shutil.copyfile(contracts/'oulad_features_v1.schema.json',destination/'feature_schema.json')
    shutil.copyfile(processed/'splits_manifest.json',destination/'splits_manifest.json')
    shutil.copyfile(run/'requirements-lock.txt',destination/'requirements-lock.txt')
    origin = config.get('data_origin', 'public_dataset')
    (destination/'model_card.md').write_text('# OULAD-style research risk model\n\n'+('Synthetic demo dataset; not institutional/NTTU data. ' if origin=='synthetic' else 'Public dataset, not an institutional/NTTU model. ')+
      'Population registered at end of day28. Target Fail or later Withdrawn. '
      'Student-disjoint group split; future-presentation generalization NOT evaluated. '
      'No claim of causal intervention or improved GPA.\n\nSelection: '+selection['selection_rule']+
      '\n\nBeats Dummy AP on dev: '+str(selection['beats_dummy_ap'])+
      '\n\nFinal test executed: '+str(final_metrics is not None)+'\n',encoding='utf-8')
    env=environment()
    manifest={'contract_version':'1.0.0','model_id':'oulad-risk-'+selection['selected']['model'].replace('_','-'),
      'model_version':model_version,'domain_id':'oulad','target_id':'non_completion_at_end',
      'target_description':'End-of-module Fail or withdrawal after day28, among registered students at cutoff',
      'positive_label':1,'cutoff_day':28,'feature_schema_id':'oulad_risk_day28','feature_schema_version':'1.0.0',
      'feature_order':list(FEATURE_ORDER),'advisor_core_version':env['packages']['sic-advisor-core'],
      'source_commit':commit,'trained_at':selection['trained_at'],'validation_level':'final_test' if final_metrics else 'dev_only',
      'environment':{k:env[k] for k in ['python_version','platform','packages']},
      'dataset_sha256':split['dataset_sha256'],'split_sha256':sha(processed/'splits_manifest.json'),
      'calibration_method':'none','alert_threshold':threshold,'parity_absolute_tolerance':1e-6,
      'explanation':{'method':explain['method'],'explained_output':explain['explained_output'],'class_label':1,
        'config_file':'explanation_config.json','background_file':None,'base_model_file':None,'calibration_note':explain['calibration_note']},
      'files':{p.name:{'sha256':sha(p),'size_bytes':p.stat().st_size} for p in destination.iterdir() if p.is_file()}}
    Draft202012Validator(load(contracts/'model_manifest.schema.json'),format_checker=FormatChecker()).validate(manifest)
    save(destination/'manifest.json',manifest)
    return manifest


def final_evaluate(run,processed,approval_path):
    run,processed=Path(run),Path(processed)
    selection,model=selected_model(run)
    approval=load(approval_path)
    if (approval.get('approved') is not True or not approval.get('owner')
            or approval.get('selected_run_sha256') != sha(run/'selected_run.json')
            or approval.get('selected_model_sha256') != selection['selected']['sha256']):
        raise ValueError('FINAL_FREEZE_REQUIRED: approve the exact selected_run and selected model hashes')
    split=load(processed/'splits_manifest.json')
    if sha(processed/'splits_manifest.json')!=selection['splits_manifest_sha256'] or sha(processed/'test.jsonl')!=split['files']['test']:
        raise ValueError('TEST_OR_SPLIT_CHANGED')
    marker=run/'FINAL_TEST_STARTED.json'
    # Exclusive marker before reading labels: failed runs require a disclosed new protocol, not silent reruns.
    with marker.open('x',encoding='utf-8') as f:
        json.dump({'selected_run_sha256':sha(run/'selected_run.json'),
                   'selected_model_sha256':selection['selected']['sha256'],
                   'status':'started'},f)
    X,y=matrix(read_jsonl(processed/'test.jsonl'))
    result=metrics(y,probability(model,X),selection['selected']['metrics']['threshold'])
    result['selected_run_sha256']=sha(run/'selected_run.json')
    result['selected_model_sha256']=selection['selected']['sha256']
    save(run/'final_metrics.json',result)
    return result
