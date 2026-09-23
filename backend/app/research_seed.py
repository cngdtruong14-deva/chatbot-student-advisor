"""Import approved smoke records as separately labelled research cases.

Student profiles are never changed.  The domain flag selects either the
existing OULAD research receipt or the isolated synthetic Academic Demo v2
receipt.
"""
import argparse
import json
from app import ai_runtime
from app.api import ResearchFeatures,save_research_features
from app.store import transaction,one

def main(domain_id="oulad"):
    approved=ai_runtime.approved_bundle(domain_id)
    if not approved:raise ValueError('APPROVED_MODEL_REQUIRED')
    with transaction() as db:
        user=one(db,"SELECT id,role FROM app.users WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
    if not user:raise ValueError('ADMIN_REQUIRED')
    count=0
    for line in (approved['bundle']/'smoke_inputs.jsonl').read_text().splitlines():
        record=json.loads(line)
        if record['domain_id'] != domain_id:
            raise ValueError('DOMAIN_MISMATCH')
        if domain_id == 'oulad' and record['data_origin'] != 'public_dataset':
            raise ValueError('DOMAIN_ORIGIN_MISMATCH')
        if domain_id == 'academic_demo_v2' and record['data_origin'] != 'synthetic':
            raise ValueError('DOMAIN_ORIGIN_MISMATCH')
        with transaction() as db:
            case=one(db,'''INSERT INTO app.research_cases(owner_user_id,source_case_key,domain_id,data_origin)
              VALUES(:uid,:key,:domain,:origin) ON CONFLICT(owner_user_id,source_case_key) DO NOTHING RETURNING id''',uid=user['id'],key=record['case_id'],domain=domain_id,origin=record['data_origin'])
            if not case:case=one(db,'SELECT id FROM app.research_cases WHERE owner_user_id=:uid AND source_case_key=:key',uid=user['id'],key=record['case_id'])
        record['case_id']=str(case['id'])
        save_research_features(case['id'],ResearchFeatures(**record),user);count+=1
    print(f'Imported {count} {domain_id} smoke cases; no student profiles changed.')

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', default='oulad', choices=sorted(ai_runtime.ACTIVE_RECEIPT_BY_DOMAIN))
    args = parser.parse_args()
    main(args.domain)
