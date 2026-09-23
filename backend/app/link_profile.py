"""Transactional, idempotent profile link for student demo accounts.

Usage:
    python -m app.link_profile <target_student_id_or_code> <user_email> --confirm LINK_PROFILE_V2
"""
import sys
import json
from uuid import UUID
from app.store import transaction, one, rows, run

def link_profile(target_code: str, email: str, confirm: str, *, full_name: str = "Sinh viên mô phỏng",
                 curriculum_code: str = "DEMO-CS", curriculum_version: str = "1",
                 cohort_code: str = "DEMO-2026"):
    """Create one account-owned synthetic profile; never transfer ownership."""
    if confirm != 'LINK_PROFILE_V2':
        raise ValueError('CONFIRM_REQUIRED: pass --confirm LINK_PROFILE_V2')

    with transaction() as db:
        user = one(db, "SELECT id,email,role FROM app.users WHERE email=:email FOR UPDATE", email=email)
        if not user:
            raise ValueError(f'USER_NOT_FOUND: {email}')
        if user['role'] != 'student':
            raise ValueError(f'USER_ROLE_INVALID: {email} is not a student')

        owned = one(db, "SELECT id,student_code FROM app.students WHERE user_id=:uid FOR UPDATE", uid=user['id'])
        if owned:
            if owned['student_code'] != target_code:
                raise ValueError(f'USER_ALREADY_LINKED: {email} linked to different student {owned["student_code"]}')
            return {'status': 'idempotent', 'user_id': str(user['id']), 'student_id': str(owned['id']),
                    'student_code': owned['student_code'], 'message': f'{email} already owns {target_code}'}

        claimed = one(db, "SELECT id,user_id FROM app.students WHERE domain_id='demo_academic' AND student_code=:code FOR UPDATE", code=target_code)
        if claimed:
            raise ValueError(f'STUDENT_ALREADY_LINKED: {target_code} is already owned by user {claimed["user_id"]}')

        curriculum = one(db, "SELECT id FROM app.curricula WHERE code=:code AND version=:version",
                         code=curriculum_code, version=curriculum_version)
        if not curriculum:
            raise ValueError(f'CURRICULUM_NOT_FOUND: {curriculum_code}/{curriculum_version}')
        cohort = one(db, "SELECT id,curriculum_id FROM app.cohorts WHERE code=:code", code=cohort_code)
        if not cohort or cohort['curriculum_id'] != curriculum['id']:
            raise ValueError(f'COHORT_NOT_FOUND: {cohort_code}')

        student = one(db, """INSERT INTO app.students
            (user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
            VALUES(:uid,:code,:name,:curriculum,:cohort,:cohort_id,'demo_academic','synthetic')
            RETURNING id,student_code""", uid=user['id'], code=target_code, name=full_name,
            curriculum=curriculum['id'], cohort=cohort_code, cohort_id=cohort['id'])
        return {'status': 'created', 'user_id': str(user['id']), 'student_id': str(student['id']),
                'student_code': student['student_code'], 'message': f'Created {target_code} for {email}'}

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('target')
    p.add_argument('email')
    p.add_argument('--confirm', required=True)
    args = p.parse_args()

    try:
        result = link_profile(args.target, args.email, args.confirm)
        print(json.dumps(result, indent=2))
        sys.exit(0)
    except Exception as e:
        print(json.dumps({'error': str(e)}, indent=2), file=sys.stderr)
        sys.exit(1)

