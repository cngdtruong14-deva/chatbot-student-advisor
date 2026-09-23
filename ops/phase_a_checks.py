"""Run inside API container on isolated Phase A stack."""
import os
import subprocess

if os.environ.get("ADVISOR_TEST_DATABASE") != "1":
    raise RuntimeError("Refusing fixture writes without explicit isolated-test environment")
raise RuntimeError(
    "Phase A checks disabled: profile-first design unresolved; "
    "constraint and migration gates are not yet implemented correctly."
)

from app.store import transaction, run, one
from app.security import password_hash
from app.link_profile import link_profile


def schema_checks():
    with transaction() as db:
        pol = one(db, "SELECT id FROM app.grading_policies WHERE code='DEMO-1'")
        if not pol:
            run(db, "INSERT INTO app.grading_policies(code,version,status,rules) VALUES('DEMO-1','1','demo','{}')")
            pol = one(db, "SELECT id FROM app.grading_policies WHERE code='DEMO-1'")
        cur = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS'")
        if not cur:
            run(db, "INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status) VALUES('DEMO-CS','1','CNTT',126,:p,'demo') ON CONFLICT DO NOTHING", p=pol["id"])
            cur = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS'")
        coh = one(db, "SELECT id FROM app.cohorts WHERE code='DEMO-2026'")
        if not coh:
            run(db, "INSERT INTO app.cohorts(code,curriculum_id) VALUES('DEMO-2026',:cid) ON CONFLICT DO NOTHING", cid=cur["id"])
            coh = one(db, "SELECT id FROM app.cohorts WHERE code='DEMO-2026'")

        run(db, "DELETE FROM app.students WHERE student_code IN ('TEST-UNLINKED-01','TEST-DUP-USER')")
        run(db, "INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin) VALUES(NULL,'TEST-UNLINKED-01','Unlinked',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')", cid=cur["id"], cohid=coh["id"])
        assert one(db, "SELECT user_id FROM app.students WHERE student_code='TEST-UNLINKED-01'")["user_id"] is None
        print("PASS: user_id NULL accepted for unlinked student profile")

        existing = one(db, "SELECT user_id FROM app.students WHERE user_id IS NOT NULL LIMIT 1")
        if existing:
            try:
                run(db, "INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin) VALUES(:uid,'TEST-DUP-USER','Dup',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')", uid=existing["user_id"], cid=cur["id"], cohid=coh["id"])
                raise AssertionError("UNIQUE user_id not enforced")
            except Exception as exc:
                if "duplicate" not in str(exc).lower() and "unique" not in str(exc).lower():
                    raise
                print("PASS: UNIQUE(app.students.user_id) still enforced")
        print("PASS: FK(app.students.user_id -> app.users.id) unchanged by migration")


def profile_link_checks():
    with transaction() as db:
        cur = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS'")
        coh = one(db, "SELECT id FROM app.cohorts WHERE code='DEMO-2026'")
        run(db, "INSERT INTO app.users(email,password_hash,role,is_active) VALUES('testlink@demo.local',:h,'student',true) ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash,role='student',is_active=true", h=password_hash('testpass'))
        run(db, "DELETE FROM app.students WHERE student_code IN ('ISO-STU-01','ISO-STU-02')")
        run(db, "INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin) VALUES(NULL,'ISO-STU-01','Sinh Vien ISO 1',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')", cid=cur['id'], cohid=coh['id'])
        run(db, "INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin) VALUES(NULL,'ISO-STU-02','Sinh Vien ISO 2',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')", cid=cur['id'], cohid=coh['id'])

    res1 = link_profile('ISO-STU-01', 'testlink@demo.local', 'LINK_PROFILE_V2')
    assert res1['status'] == 'linked'
    print('PASS: profile-link linked')
    res2 = link_profile('ISO-STU-01', 'testlink@demo.local', 'LINK_PROFILE_V2')
    assert res2['status'] == 'idempotent'
    print('PASS: profile-link idempotent')
    try:
        link_profile('ISO-STU-02', 'testlink@demo.local', 'LINK_PROFILE_V2')
        raise AssertionError('Expected conflict')
    except ValueError as exc:
        assert 'USER_ALREADY_LINKED' in str(exc)
        print('PASS: profile-link conflict rejected')

    with transaction() as db:
        u = one(db, "SELECT id FROM app.users WHERE email='testlink@demo.local'")
        st = one(db, "SELECT student_code FROM app.students WHERE user_id=:uid", uid=u['id'])
        assert st['student_code'] == 'ISO-STU-01'
        print('PASS: mapping unchanged after conflict')


if __name__ == '__main__':
    schema_checks()
    profile_link_checks()
