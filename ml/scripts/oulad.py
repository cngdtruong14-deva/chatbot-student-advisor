"""OULAD audit and normalized CSV adapter. No fitting, DB access or provider keys."""
import hashlib
from pathlib import Path
import pandas as pd
from advisor_core.ml_boundary import build_features, validate_features
from .common import load, save, sha, jsonl, require_approval

KEY = ['code_module','code_presentation','id_student']
FILES = ['courses.csv','assessments.csv','studentInfo.csv','studentRegistration.csv','studentAssessment.csv','studentVle.csv','vle.csv']


def read(raw, name):
    return pd.read_csv(Path(raw)/name, dtype={'id_student':str,'id_assessment':str,'id_site':str})


def source_hashes(raw):
    return {name: sha(Path(raw)/name) for name in FILES}


def population(raw, cutoff):
    info, registration = read(raw,'studentInfo.csv'), read(raw,'studentRegistration.csv')
    duplicate_keys = set()
    for frame in [info, registration]:
        duplicate_keys.update(map(tuple, frame.loc[frame.duplicated(KEY, keep=False), KEY].to_numpy()))
    # The supplied synthetic source contains conflicting duplicate identity keys.
    # Quarantine every occurrence from both sides; never choose a survivor.
    if duplicate_keys:
        mask_info = info[KEY].apply(tuple, axis=1).isin(duplicate_keys)
        mask_registration = registration[KEY].apply(tuple, axis=1).isin(duplicate_keys)
        info, registration = info.loc[~mask_info].copy(), registration.loc[~mask_registration].copy()
    frame = info.merge(registration, on=KEY, how='left', validate='one_to_one', indicator=True)
    registered = pd.to_numeric(frame['date_registration'], errors='coerce')
    withdrawn = pd.to_numeric(frame['date_unregistration'], errors='coerce')
    valid = frame['_merge'].eq('both') & registered.notna() & registered.le(cutoff)
    valid &= withdrawn.isna() | withdrawn.gt(cutoff)
    valid &= frame['final_result'].isin(['Pass','Distinction','Fail','Withdrawn'])
    # Unknown withdrawal timing cannot establish the at-risk population.
    valid &= ~((frame['final_result']=='Withdrawn') & withdrawn.isna())
    valid &= ~((frame['final_result']!='Withdrawn') & withdrawn.notna())
    valid &= registered.mod(1).eq(0) & (withdrawn.isna() | withdrawn.mod(1).eq(0))
    eligible = frame.loc[valid].copy()
    frame.attrs['quarantined_duplicate_keys'] = len(duplicate_keys)
    eligible['target'] = eligible['final_result'].isin(['Fail','Withdrawn']).astype(int)
    return frame, eligible


def audit(raw, output, config):
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    hashes = source_hashes(raw)
    all_rows, eligible = population(raw,config['cutoff_day'])
    report = {'dataset':config['dataset'],'data_origin':config['data_origin'],'source_url':config['source_url'],
      'license':config['license'],'source_hashes':hashes,'candidate_cutoff':config['cutoff_day'],
      'target_id':config['target_id'],'student_info_rows':len(all_rows),'eligible_rows':len(eligible),
      'excluded_or_quarantined_rows':len(all_rows)-len(eligible),
      'quarantined_duplicate_identity_keys':all_rows.attrs.get('quarantined_duplicate_keys',0),
      'eligible_class_counts':{str(k):int(v) for k,v in eligible['target'].value_counts().items()},
      'module_presentations':eligible.groupby(['code_module','code_presentation']).size().reset_index(name='count').to_dict('records'),
      'missing':{k:int(v) for k,v in all_rows.isna().sum().items()},
      'approved':False,'next_action':'Owner reviews source completeness, exclusion rules, day28 and labels; approve exact report hash'}
    save(output/'data_audit.json',report)
    save(output/'approval.template.json',{'approved':False,'owner':'','audit_sha256':sha(output/'data_audit.json'),
                                        'cutoff_day':28,'target_id':'non_completion_at_end','source_completeness_verified':False})
    (output/'data_dictionary.md').write_text('# OULAD candidate features\n\nSource tables: '+', '.join(FILES)+
      '\n\nNo assessment scores are predictors. Missing source is not zero activity. '
      'Population: registration <=28, withdrawal absent or >28; inconsistent outcomes/timing quarantined. '
      'Label 1 = Fail or post-cutoff Withdrawn; 0 = Pass or Distinction.\n',encoding='utf-8')
    return report


def features_and_splits(raw, output, audit_dir, approval_path, config, schema_path):
    audit_dir, output = Path(audit_dir), Path(output)
    approval = require_approval(approval_path,sha(audit_dir/'data_audit.json'))
    if approval.get('cutoff_day')!=28 or approval.get('target_id')!='non_completion_at_end' or approval.get('source_completeness_verified') is not True:
        raise ValueError('TARGET_CUTOFF_OR_SOURCE_APPROVAL_REQUIRED')
    if config['cutoff_day']!=28 or config['target_id']!='non_completion_at_end':
        raise ValueError('CONTRACT_MISMATCH')
    if source_hashes(raw) != load(audit_dir/'data_audit.json')['source_hashes']:
        raise ValueError('RAW_FILES_CHANGED_SINCE_AUDIT')
    if output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS: use a new run directory')
    _, eligible = population(raw,28)
    if config['split_rule']!='group_hash_70_15_15':
        raise ValueError('UNSUPPORTED_SPLIT_RULE')
    if eligible['num_of_prev_attempts'].isna().any() or (eligible['num_of_prev_attempts']%1!=0).any() or (eligible['num_of_prev_attempts']<0).any():
        raise ValueError('INVALID_STATIC_PREVIOUS_ATTEMPTS')
    if eligible['studied_credits'].isna().any() or (eligible['studied_credits']<=0).any():
        raise ValueError('INVALID_STATIC_CREDITS')
    identifiers = sorted(eligible.id_student.unique(), key=lambda uid: hashlib.sha256(f"sample:{config['seed']}:{uid}".encode()).hexdigest())
    limit = config['sample_students']
    if limit:
        identifiers = identifiers[:limit]
    eligible = eligible[eligible.id_student.isin(identifiers)].copy()
    keys = set(map(tuple,eligible[KEY].to_numpy()))
    events = {k:[] for k in keys}
    for chunk in pd.read_csv(Path(raw)/'studentVle.csv',chunksize=200000,dtype={'id_student':str,'id_site':str}):
        chunk = chunk[chunk.id_student.isin(identifiers)]
        for row in chunk.itertuples(index=False):
            key=(row.code_module,row.code_presentation,row.id_student)
            if key in keys:
                if pd.isna(row.date) or pd.isna(row.sum_click) or row.date%1 or row.sum_click%1 or row.sum_click<0:
                    raise ValueError('INVALID_VLE_EVENT')
                # The shared builder is the only cutoff/counting implementation.
                events[key].append({'day':int(row.date),'sum_click':int(row.sum_click)})
    assessments = read(raw,'assessments.csv')
    if assessments.id_assessment.duplicated().any():
        raise ValueError('DUPLICATE_ASSESSMENT_ID')
    submitted = read(raw,'studentAssessment.csv')
    submitted = submitted[submitted.id_student.isin(identifiers)].merge(assessments,on='id_assessment',how='left',validate='many_to_one',indicator=True)
    if submitted['_merge'].ne('both').any():
        raise ValueError('UNKNOWN_ASSESSMENT')
    assessment_events = {k:[] for k in keys}
    for row in submitted.itertuples(index=False):
        key=(row.code_module,row.code_presentation,row.id_student)
        if key in keys:
            if pd.isna(row.date_submitted) or row.date_submitted%1 or row.is_banked not in [0,1]:
                raise ValueError('INVALID_SUBMISSION_EVENT')
            assessment_events[key].append({'assessment_id':str(row.id_assessment),'submitted_day':int(row.date_submitted),
                                           'is_banked':bool(row.is_banked),'is_exam':row.assessment_type=='Exam'})
    groups, records = {}, {'train':[], 'dev':[], 'test':[]}
    for row in eligible.itertuples(index=False):
        key=(row.code_module,row.code_presentation,row.id_student)
        group=hashlib.sha256(f"student:{config['seed']}:{row.id_student}".encode()).hexdigest()
        bucket=int(group[:8],16)%100
        split='train' if bucket<70 else 'dev' if bucket<85 else 'test'
        groups[group]=split
        record=build_features('oulad',{'case_id':hashlib.sha256('|'.join(key).encode()).hexdigest(), 'data_origin':config['data_origin'],
          'static':{'registration_day':int(row.date_registration),'withdrawal_day':None if pd.isna(row.date_unregistration) else int(row.date_unregistration),
                    'num_of_prev_attempts':int(row.num_of_prev_attempts),'studied_credits':float(row.studied_credits)},
          'vle':events[key],'assessments':assessment_events[key]},28,
          {'static_verified':True,'vle_complete':True,'assessment_complete':True})
        validate_features(record,schema_path,allow_synthetic=config['data_origin']=='synthetic')
        records[split].append({'record':record,'group_id':group,'target':int(row.target)})
    for split,data in records.items():
        if len(data)<10 or {r['target'] for r in data}!={0,1}:
            raise ValueError(f'INSUFFICIENT_SPLIT_{split}: increase sample before training, do not resplit after viewing test metrics')
    output.mkdir(parents=True)
    for split,data in records.items():
        jsonl(output/f'{split}.jsonl',data)
    save(output/'splits_manifest.json',{'rule':config['split_rule'],'seed':config['seed'],'student_disjoint':True,
      'temporal_generalization_test':False,'groups':groups,'files':{s:sha(output/f'{s}.jsonl') for s in records},
      'counts':{s:len(v) for s,v in records.items()},'audit_sha256':sha(audit_dir/'data_audit.json'),
      'dataset_sha256':hashlib.sha256(str(sorted(source_hashes(raw).items())).encode()).hexdigest()})
    save(output/'leakage_checks.json',{'group_overlap':0,'cutoff':28,'outcome_predictors':[],
      'feature_code':'advisor_core.ml_boundary.build_features','test_labels_separate':True,
      'limitation':'Group split does not estimate future-presentation performance'})
    return {s:len(v) for s,v in records.items()}
