"""Create an explicitly synthetic, cutoff-safe event dataset from Academic Demo v2 outcomes.

Event values are generated from pre-cutoff latent engagement and prior-history
proxies, never copied from the current attempt's final score.  This is a demo
simulator, not evidence that a real LMS signal has predictive value.
"""
import argparse, hashlib, json, random
from collections import defaultdict
from pathlib import Path

FEATURES = ['prior_gpa_4','prior_attempts','attendance_rate_0_28','missed_sessions_0_28','submission_rate_0_28','published_assessment_mean_0_28','lms_active_days_0_28']

def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def build(normalized, out, seed=20260912):
    out=Path(out)
    if out.exists(): raise ValueError('IMMUTABLE_OUTPUT_EXISTS')
    source=Path(normalized); rng=random.Random(seed); rows=[json.loads(x) for x in source.read_text(encoding='utf-8').splitlines()]
    by_student=defaultdict(list)
    for row in rows: by_student[row['student_code']].append(row)
    records=[]
    for student, attempts in by_student.items():
        attempts.sort(key=lambda r:(r['semester_code'],r['attempt'],r['course']))
        prior=[]
        for row in attempts:
            # A later attempt is its own risk case.  Current final score is used
            # only for the target, after all cutoff features are generated.
            prior_gpa=(sum(float(x['effective_score_4'])*float(x['credits']) for x in prior if x['gpa_bearing']) /
                       sum(float(x['credits']) for x in prior if x['gpa_bearing'])) if any(x['gpa_bearing'] for x in prior) else None
            risk=(4-(prior_gpa if prior_gpa is not None else 2.0))/4 + .12*sum(x['status']=='absent_or_barred' for x in prior[-4:])
            attendance=max(0,min(1,rng.gauss(.88-.40*risk,.10))); submission=max(0,min(1,rng.gauss(.84-.45*risk,.13)))
            active=max(0,min(29,round(rng.gauss(19-10*risk,4)))); published=max(0,min(10,rng.gauss(7.2-3.0*risk,.9)))
            features={'prior_gpa_4':prior_gpa,'prior_attempts':sum(x['course']==row['course'] for x in prior),'attendance_rate_0_28':attendance,'missed_sessions_0_28':round((1-attendance)*12),'submission_rate_0_28':submission,'published_assessment_mean_0_28':published,'lms_active_days_0_28':active}
            record={'case_id':f'{student}:{row["offering_code"]}','domain_id':'academic_demo_v2','data_origin':'synthetic','feature_schema_id':'academic_demo_v2_risk_day28','feature_schema_version':'1.0.0','cutoff_day':28,'source_completeness':{'event_generator_verified':True,'transcript_label_verified':True},'features':features}
            target=int(row['status']=='absent_or_barred' or float(row['effective_score_10'])<4)
            records.append({'group_id':student,'record':record,'target':target})
            prior.append(row)
    splits={'train':[],'dev':[],'test':[]}
    for item in records:
        bucket=int(hashlib.sha256(item['group_id'].encode()).hexdigest(),16)%100
        splits['train' if bucket<70 else 'dev' if bucket<85 else 'test'].append(item)
    if any(len({x['target'] for x in data})<2 for data in splits.values()): raise ValueError('SPLIT_CLASS_FAILURE')
    out.mkdir(); files={}
    for name,data in splits.items():
        path=out/f'{name}.jsonl'; path.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in data),encoding='utf-8'); files[name]=digest(path)
    audit={'dataset_id':'academic_demo_v2_events_v1','data_origin':'synthetic','cutoff_day':28,'feature_order':FEATURES,'source_normalized_sha256':digest(source),'seed':seed,'rows':{k:len(v) for k,v in splits.items()},'positive_prevalence':{k:sum(x['target'] for x in v)/len(v) for k,v in splits.items()},'limitations':['Events are generated synthetic proxies; no real LMS/attendance claim.','Current final score is target only; it is not a feature.']}
    (out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8'); return audit

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('normalized');p.add_argument('output');a=p.parse_args();print(json.dumps(build(a.normalized,a.output),indent=2))
