"""One-shot, local, reproducible synthetic OULAD-style training run.

Creates new output only. The caller must pass the exact checked-out source commit.
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from .common import load, save, sha
from .oulad import audit, features_and_splits
from .train import train_and_select
from .package import final_evaluate, export_bundle


def run(raw, output_root, source_commit, owner):
    raw, root = Path(raw), Path(output_root)
    if root.exists() and any(root.iterdir()):
        raise ValueError('OUTPUT_ROOT_ALREADY_EXISTS')
    if len(source_commit) != 40 or any(c not in '0123456789abcdef' for c in source_commit):
        raise ValueError('INVALID_SOURCE_COMMIT')
    config = {'dataset':'synthetic_oulad_style_dataset_v1','data_origin':'synthetic',
      'source_url':'local:D:/tailieu/SIC/dataset/synthetic_oulad_style_dataset_v1',
      'license':'owner_created_synthetic_demo','target_id':'non_completion_at_end','cutoff_day':28,
      'seed':42,'sample_students':500,'split_rule':'group_hash_70_15_15','calibration_method':'none',
      'threshold_selection':'max_f1_on_dev','source_commit':source_commit,'source_commit_approved':True,
      'source_provenance':{'source_kind':'local_verified_synthetic_run','source_commit':source_commit,
                           'note':'owner-authorized local run; source data hashes recorded in audit'}}
    root.mkdir(parents=True, exist_ok=True)
    audit_dir, processed, run_dir, bundle = root/'audit', root/'processed', root/'run', root/'bundle'
    report=audit(raw,audit_dir,config)
    approval=load(audit_dir/'approval.template.json')
    approval.update({'approved':True,'owner':owner,'source_completeness_verified':True,
                     'approval_context':'Owner authorized one-shot synthetic demonstration training on 2026-09-12.'})
    save(audit_dir/'approval.json',approval)
    counts=features_and_splits(raw,processed,audit_dir,audit_dir/'approval.json',config,Path('/contracts/oulad_features_v1.schema.json'))
    selection=train_and_select(processed,run_dir,config)
    if selection['selected']['model']=='dummy' or not selection['beats_dummy_ap']:
        raise ValueError('NO_DEPLOYABLE_MODEL_BEATS_DUMMY')
    freeze=load(run_dir/'freeze_approval.template.json')
    freeze.update({'approved':True,'owner':owner,'approval_context':'Owner-authorized one-shot synthetic final evaluation on 2026-09-12.'})
    save(run_dir/'freeze_approval.json',freeze)
    final=final_evaluate(run_dir,processed,run_dir/'freeze_approval.json')
    manifest=export_bundle(run_dir,processed,bundle,Path('/contracts'),'synthetic-oulad-v1-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),final)
    receipt={'approved':True,'owner':owner,'bundle_directory':bundle.name,'manifest_sha256':sha(bundle/'manifest.json'),
             'approval_context':'Owner explicitly requested artifact creation and activation preparation on 2026-09-12.',
             'data_origin':'synthetic','created_at':datetime.now(timezone.utc).isoformat()}
    save(root/'activation_receipt.json',receipt)
    save(root/'run_report.json',{'status':'final_test_complete','counts':counts,'audit_sha256':sha(audit_dir/'data_audit.json'),
      'selected_model':selection['selected']['model'],'dev_metrics':selection['selected']['metrics'],'final_metrics':final,
      'bundle_manifest_sha256':receipt['manifest_sha256'],'bundle':bundle.name,'data_origin':'synthetic',
      'source_commit':source_commit,'dataset_source_hash':hashlib.sha256(json.dumps(report['source_hashes'],sort_keys=True).encode()).hexdigest()})
    return load(root/'run_report.json')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('raw'); parser.add_argument('output_root'); parser.add_argument('source_commit'); parser.add_argument('--owner',default='cngdt-owner')
    args=parser.parse_args()
    print(json.dumps(run(args.raw,args.output_root,args.source_commit,args.owner),ensure_ascii=True,indent=2))
