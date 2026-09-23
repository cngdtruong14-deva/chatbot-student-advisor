"""Train governed baselines for the synthetic Academic Demo v2 event simulator."""
import argparse,json,hashlib
from pathlib import Path
import joblib,pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score,precision_score,recall_score,f1_score,roc_auc_score,brier_score_loss,confusion_matrix
from build_academic_demo_v2_events import FEATURES,digest

def load(path):return [json.loads(x) for x in Path(path).read_text().splitlines()]
def xy(rows):return pd.DataFrame([x['record']['features'] for x in rows],columns=FEATURES),[x['target'] for x in rows]
def metric(y,p,t):
 q=[v>=t for v in p];return {'average_precision':average_precision_score(y,p),'precision':precision_score(y,q,zero_division=0),'recall':recall_score(y,q,zero_division=0),'f1':f1_score(y,q,zero_division=0),'roc_auc':roc_auc_score(y,p),'brier':brier_score_loss(y,p),'confusion_matrix':confusion_matrix(y,q,labels=[0,1]).tolist(),'threshold':t}
def run(processed,out):
 out=Path(out);out.mkdir();tr,dv,te=map(lambda n:load(Path(processed)/f'{n}.jsonl'),['train','dev','test']);X,y=xy(tr);Xd,yd=xy(dv)
 results=[]
 for name,clf in [('dummy',DummyClassifier(strategy='prior')),('logistic_regression',LogisticRegression(max_iter=2000,random_state=42)),('random_forest',RandomForestClassifier(n_estimators=150,min_samples_leaf=5,max_depth=10,random_state=42,n_jobs=2))]:
  m=Pipeline([('imputer',SimpleImputer(strategy='median',keep_empty_features=True)),('scaler',StandardScaler()),('classifier',clf)]);m.fit(X,y);p=m.predict_proba(Xd)[:,list(m.classes_).index(1)]; t=max([i/100 for i in range(5,96)],key=lambda z:f1_score(yd,p>=z,zero_division=0));path=out/f'{name}.joblib';joblib.dump(m,path);results.append({'model':name,'path':path.name,'sha256':digest(path),'metrics':metric(yd,p,t)})
 sel=max(results,key=lambda r:(r['metrics']['average_precision'],r['model']=='logistic_regression')); model=joblib.load(out/sel['path']);Xt,yt=xy(te);p=model.predict_proba(Xt)[:,list(model.classes_).index(1)];final=metric(yt,p,sel['metrics']['threshold'])
 report={'status':'final_test_complete','dataset':'academic_demo_v2_events_v1','data_origin':'synthetic','domain_id':'academic_demo_v2','target_id':'non_completion_at_end','cutoff_day':28,'feature_order':FEATURES,'comparison_dev':results,'selected':sel,'final_test':final,'limitations':['Synthetic event simulator only. Not activated or applicable to institutional records until a reviewed bundle/runtime contract exists.']};(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('processed');p.add_argument('output');a=p.parse_args();print(json.dumps(run(a.processed,a.output),indent=2))
