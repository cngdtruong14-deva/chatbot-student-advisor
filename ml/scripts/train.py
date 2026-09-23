"""Train/dev only selection. Test labels are never opened by train_and_select."""
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score, precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix, brier_score_loss
from sklearn.calibration import calibration_curve
from advisor_core.ml_boundary import FEATURE_ORDER
from .common import save, load, sha, read_jsonl, freeze, environment


def matrix(records):
    return pd.DataFrame([r['record']['features'] for r in records], columns=list(FEATURE_ORDER)).astype(float), np.asarray([r['target'] for r in records])


def probability(model, X):
    classes=list(model.classes_)
    if classes.count(1)!=1:
        raise ValueError('POSITIVE_CLASS_MISSING')
    p=np.asarray(model.predict_proba(X))[:,classes.index(1)]
    if not np.isfinite(p).all() or ((p<0)|(p>1)).any():
        raise ValueError('INVALID_PROBABILITY')
    return p


def metrics(y,p,threshold):
    predicted=p>=threshold
    frac,mean=calibration_curve(y,p,n_bins=10,strategy='uniform')
    return {'average_precision':float(average_precision_score(y,p)),
      'precision':float(precision_score(y,predicted,zero_division=0)), 'recall':float(recall_score(y,predicted,zero_division=0)),
      'f1':float(f1_score(y,predicted,zero_division=0)), 'roc_auc':float(roc_auc_score(y,p)),
      'confusion_matrix':confusion_matrix(y,predicted,labels=[0,1]).tolist(), 'brier':float(brier_score_loss(y,p)),
      'calibration':{'mean_predicted_probability':mean.tolist(),'fraction_positive':frac.tolist()},
      'threshold':float(threshold),'sample_count':len(y),'positive_prevalence':float(np.mean(y))}


def train_and_select(processed, output, config):
    processed,output=Path(processed),Path(output)
    if output.exists():
        raise ValueError('RUN_ALREADY_EXISTS')
    split=load(processed/'splits_manifest.json')
    for name in ['train','dev']:
        if sha(processed/f'{name}.jsonl')!=split['files'][name]:
            raise ValueError('SPLIT_HASH_MISMATCH')
    train,dev=read_jsonl(processed/'train.jsonl'),read_jsonl(processed/'dev.jsonl')
    if {r['group_id'] for r in train}&{r['group_id'] for r in dev}:
        raise ValueError('GROUP_LEAKAGE')
    X,y=matrix(train); Xd,yd=matrix(dev)
    if set(y)!={0,1} or set(yd)!={0,1}:
        raise ValueError('BOTH_CLASSES_REQUIRED')
    estimators={'dummy':DummyClassifier(strategy='prior'),
      'logistic_regression':LogisticRegression(max_iter=2000,random_state=config['seed']),
      'random_forest':RandomForestClassifier(n_estimators=150,max_depth=10,min_samples_leaf=5,n_jobs=2,random_state=config['seed'])}
    output.mkdir(parents=True)
    results=[]
    for name,estimator in estimators.items():
        model=Pipeline([('imputer',SimpleImputer(strategy='median',keep_empty_features=True)),
                        ('scaler',StandardScaler()),('classifier',estimator)])
        model.fit(X,y)
        p=probability(model,Xd)
        thresholds=np.linspace(0.05,0.95,91)
        threshold=max(thresholds,key=lambda t:(f1_score(yd,p>=t,zero_division=0),t))
        result=metrics(yd,p,threshold)
        model_path=output/f'{name}.joblib'; joblib.dump(model,model_path)
        results.append({'model':name,'path':model_path.name,'sha256':sha(model_path),'metrics':result})
    selected=max(results,key=lambda r:(r['metrics']['average_precision'],r['model']=='logistic_regression'))
    dummy=next(r for r in results if r['model']=='dummy')
    selection={'validation_level':'dev_only','test_metrics':None,'test_status':'not_evaluated',
      'selected':selected,'comparison':results,'beats_dummy_ap':selected['metrics']['average_precision']>dummy['metrics']['average_precision'],
      'selection_rule':'max AP on dev; threshold max F1 on dev grid; no calibration fitted',
      'calibration_method':'none','config':config,'splits_manifest_sha256':sha(processed/'splits_manifest.json'),
      'environment':environment(),'trained_at':datetime.now(timezone.utc).isoformat()}
    save(output/'selected_run.json',selection)
    pd.DataFrame([{'model':r['model'],**{k:v for k,v in r['metrics'].items() if isinstance(v,(float,int))}} for r in results]).to_csv(output/'comparison_dev.csv',index=False)
    freeze(output/'requirements-lock.txt')
    # Freeze both the selection document and the exact selected pipeline.  The
    # two hashes deliberately have different names: a selection-file hash alone
    # is not sufficiently clear during a hand-off or a final-test audit.
    save(output/'freeze_approval.template.json',{
      'approved':False,
      'owner':'',
      'selected_run_sha256':sha(output/'selected_run.json'),
      'selected_model_sha256':selected['sha256'],
    })
    return selection
