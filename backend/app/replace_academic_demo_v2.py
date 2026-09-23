"""Explicit destructive replacement of synthetic academic-demo records only.

Requires a reviewed backup and exact confirmation. It never touches database
roles, secrets, UTT-test documents, volumes or model binaries.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from app.store import transaction, one, rows, run

CONFIRM = 'REPLACE_ACADEMIC_DEMO_V2'
NON_GPA = {'PE101', 'PE201', 'PE301', 'GEN402'}


def csv_rows(root, name):
    with (Path(root) / f'{name}.csv').open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace(root, confirmation):
    if confirmation != CONFIRM:
        raise ValueError('EXACT_CONFIRMATION_REQUIRED')
    root = Path(root).resolve(strict=True)
    required = ['users','students','cohorts','courses','curricula','curriculum_courses','semesters',
                'offerings','prerequisites','enrollments','grade_components','grade_component_scores']
    source = {name: csv_rows(root, name) for name in required}
    if len(source['students']) != 1000 or any(row['data_origin'] != 'synthetic' for row in source['students']):
        raise ValueError('UNEXPECTED_SOURCE_POPULATION')
    if not NON_GPA <= {row['code'] for row in source['courses']}:
        raise ValueError('NON_GPA_COURSE_MISSING')
    hashes = {f'{name}.csv': sha(root/f'{name}.csv') for name in required}
    offerings = {r['offering_code']: r for r in source['offerings']}
    if any(row['offering_code'] not in offerings for row in source['enrollments']):
        raise ValueError('UNKNOWN_OFFERING')
    if any(row['final_score'] and not 0 <= float(row['final_score']) <= 10 for row in source['enrollments']):
        raise ValueError('INVALID_SCORE')
    policy_rules = {'policy_version':'ACADEMIC-DEMO-2.0.0','data_origin':'synthetic',
      'retake_rule':'latest_resolved_attempt_replaces_previous_even_if_lower',
      'absent_or_barred':'incomplete with effective 0 until later attempt',
      'non_gpa_courses':sorted(NON_GPA),'pass_score_10':4,
      'gpa_4_bands':[[0,0],[4,1],[5,1.5],[5.5,2],[6.5,2.5],[7,3],[8,3.5],[8.5,4]]}
    with transaction() as db:
        # Preserve existing non-student accounts so the known local admin can operate.
        run(db, 'DELETE FROM app.refresh_sessions WHERE user_id IN (SELECT id FROM app.users WHERE role=\'student\')')
        run(db, 'DELETE FROM app.chat_messages')
        run(db, 'DELETE FROM app.chat_sessions')
        run(db, 'DELETE FROM app.goals')
        run(db, 'DELETE FROM app.advisor_assignments')
        run(db, 'DELETE FROM app.grade_components')
        run(db, 'DELETE FROM app.enrollments')
        run(db, 'DELETE FROM app.assessment_components')
        run(db, 'DELETE FROM app.course_offerings')
        run(db, 'DELETE FROM app.prerequisites')
        run(db, 'DELETE FROM app.curriculum_courses')
        run(db, 'DELETE FROM app.students')
        run(db, 'DELETE FROM app.cohorts')
        run(db, 'DELETE FROM app.courses WHERE domain_id=\'demo_academic\'')
        run(db, 'DELETE FROM app.semesters')
        run(db, 'DELETE FROM app.curricula')
        run(db, 'DELETE FROM app.grading_policies')
        run(db, 'UPDATE app.users SET is_active=false WHERE role=\'student\'')
        # Prevent the old synthetic policy corpus from answering against the new policy.
        run(db, "UPDATE app.document_versions SET status='retired' WHERE scope_key='demo_academic' AND status='active'")
        policy=one(db, "INSERT INTO app.grading_policies(code,version,status,rules) VALUES('ACADEMIC-DEMO-2','2.0.0','demo',CAST(:rules AS jsonb)) RETURNING id", rules=json.dumps(policy_rules))
        curriculum_ids={}
        for r in source['curricula']:
            item=one(db, '''INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status)
              VALUES(:code,:version,:major,:credits,:policy,'demo') RETURNING id''', code=r['code'],version=r['version'],major=r['major'],credits=r['total_required_credits'],policy=policy['id'])
            curriculum_ids[r['code']]=item['id']
        for r in source['semesters']:
            run(db, 'INSERT INTO app.semesters(code,start_date,end_date) VALUES(:code,:start,:end)',code=r['code'],start=r['start_date'],end=r['end_date'])
        semester_ids={r['code']:r['id'] for r in rows(db,'SELECT id,code FROM app.semesters')}
        course_ids={}
        for r in source['courses']:
            item=one(db, "INSERT INTO app.courses(code,title,domain_id) VALUES(:code,:title,'demo_academic') RETURNING id",code=r['code'],title=r['title'])
            course_ids[r['code']]=item['id']
        for r in source['curriculum_courses']:
            run(db, '''INSERT INTO app.curriculum_courses(curriculum_id,course_id,credits,required,recommended_term_no)
              VALUES(:curriculum,:course,:credits,:required,:term)''', curriculum=curriculum_ids[r['curriculum_code']],course=course_ids[r['course_code']],credits=r['credits'],required=r['required'].lower()=='true',term=r['recommended_term_no'])
        cohort_ids={}
        for r in source['cohorts']:
            item=one(db,'INSERT INTO app.cohorts(code,curriculum_id) VALUES(:code,:curriculum) RETURNING id',code=r['code'],curriculum=curriculum_ids[r['curriculum_code']])
            cohort_ids[r['code']]=item['id']
        offering_ids={}
        for r in source['offerings']:
            item=one(db,'''INSERT INTO app.course_offerings(course_id,semester_id,policy_id,credits,is_open)
              VALUES(:course,:semester,:policy,:credits,:open) RETURNING id''',course=course_ids[r['course_code']],semester=semester_ids[r['semester_code']],policy=policy['id'],credits=r['credits'],open=r['is_open'].lower()=='true')
            offering_ids[r['offering_code']]=item['id']
        for r in source['prerequisites']:
            run(db,'''INSERT INTO app.prerequisites(curriculum_id,course_id,prerequisite_course_id,min_grade_point)
              VALUES(:curriculum,:course,:prerequisite,:point)''',curriculum=curriculum_ids[r['curriculum_code']],course=course_ids[r['course_code']],prerequisite=course_ids[r['prerequisite_course_code']],point=r['min_grade_point'])
        component_ids={}
        for r in source['grade_components']:
            item=one(db,'''INSERT INTO app.assessment_components(offering_id,code,weight,max_score,minimum_required)
              VALUES(:offering,:code,:weight,:max_score,:minimum) RETURNING id''',offering=offering_ids[r['offering_code']],code=r['component_code'],weight=r['weight'],max_score=r['max_score'],minimum=r['minimum_required'])
            component_ids[(r['offering_code'],r['component_code'])]=item['id']
        source_users={r['email']:r for r in source['users'] if r['role']=='student'}
        if set(source_users) != {r['account_email'] for r in source['students']}:
            raise ValueError('STUDENT_USER_LINK_MISMATCH')
        user_ids={}
        for email, r in source_users.items():
            item=one(db,'''INSERT INTO app.users(email,password_hash,role,is_active) VALUES(:email,:hash,'student',true)
              ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,role='student',is_active=true RETURNING id''',email=email,hash=r['password_hash'])
            user_ids[email]=item['id']
        student_ids={}
        for r in source['students']:
            item=one(db,'''INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
              VALUES(:user,:code,:name,:curriculum,:cohort,:cohort_id,'demo_academic','synthetic') RETURNING id''',user=user_ids[r['account_email']],code=r['student_code'],name='Sinh viên mô phỏng '+r['student_code'],curriculum=curriculum_ids[r['curriculum_code']],cohort=r['cohort_code'],cohort_id=cohort_ids[r['cohort_code']])
            student_ids[r['student_code']]=item['id']
        enrollment_ids={}
        for r in source['enrollments']:
            offer=offerings[r['offering_code']]
            status='graded' if r['final_score'] else 'incomplete'
            item=one(db,'''INSERT INTO app.enrollments(student_id,offering_id,course_id,attempt_no,status,final_score,recognized,minimums_met,finalized_at)
              VALUES(:student,:offering,:course,:attempt,:status,:score,false,true,:finalized) RETURNING id''',student=student_ids[r['student_code']],offering=offering_ids[r['offering_code']],course=course_ids[offer['course_code']],attempt=r['attempt_no'],status=status,score=r['final_score'] or None,finalized=r['finalized_at'] or None)
            enrollment_ids[(r['student_code'],r['offering_code'])]=item['id']
        for r in source['grade_component_scores']:
            run(db,'''INSERT INTO app.grade_components(enrollment_id,component_id,score,observed_at,available_at)
              VALUES(:enrollment,:component,:score,now(),now())''',enrollment=enrollment_ids[(r['student_code'],r['offering_code'])],component=component_ids[(r['offering_code'],r['component_code'])],score=r['score'])
        advisor=one(db,"SELECT id FROM app.users WHERE role='advisor' AND is_active ORDER BY created_at LIMIT 1")
        if advisor:
            for sid in student_ids.values():
                run(db,'INSERT INTO app.advisor_assignments(advisor_user_id,student_id) VALUES(:advisor,:student)',advisor=advisor['id'],student=sid)
        counts={name:one(db,query)['count'] for name,query in {
            'students':'SELECT count(*) AS count FROM app.students', 'courses':'SELECT count(*) AS count FROM app.courses',
            'offerings':'SELECT count(*) AS count FROM app.course_offerings','enrollments':'SELECT count(*) AS count FROM app.enrollments',
            'grade_component_scores':'SELECT count(*) AS count FROM app.grade_components'}.items()}
        expected={'students':1000,'courses':50,'offerings':292,'enrollments':24370,'grade_component_scores':80236}
        if counts!=expected: raise ValueError(f'POST_IMPORT_COUNT_MISMATCH:{counts}')
        return {'status':'replaced','counts':counts,'policy_version':'ACADEMIC-DEMO-2.0.0','source_hashes':hashes,
                'non_gpa_courses':sorted(NON_GPA),'absent_or_barred_rows':145}


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('source'); p.add_argument('--confirm',required=True)
    args=p.parse_args()
    print(json.dumps(replace(args.source,args.confirm),ensure_ascii=True))
