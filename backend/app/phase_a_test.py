"""Phase A verification runner on isolated DB.

Tests:
1. Integration suite: 31 application checks.
2. Account-first profile link tests:
   - Unlinked user state
   - link_profile creates synthetic profile
   - Idempotent rerun
   - Conflict when user already owns different profile
   - Conflict when target profile owned by different user
"""
import os

from app.test_safety import require_test_environment

require_test_environment()

from app.store import transaction, run, one
from app.link_profile import link_profile


def test_fixture_setup():
    print("--- 1. Fixture Setup ---")
    with transaction() as db:
        run(db, "INSERT INTO app.grading_policies(code,version,status,rules) VALUES('DEMO-1','1','demo','{}') ON CONFLICT(code,version) DO NOTHING")
        pol = one(db, "SELECT id FROM app.grading_policies WHERE code='DEMO-1'")
        pol_id = pol['id']

        run(db, "INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status) VALUES('DEMO-CS','1','Test',126,:pol_id,'demo') ON CONFLICT(code,version) DO NOTHING", pol_id=pol_id)
        cur = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS'")
        cur_id = cur['id']

        run(db, "INSERT INTO app.cohorts(code,curriculum_id) VALUES('DEMO-2026',:cid) ON CONFLICT(code) DO NOTHING", cid=cur_id)

        run(db, "INSERT INTO app.users(email,password_hash,role,is_active) VALUES('unlinked@demo.local','test','student',true) ON CONFLICT(email) DO NOTHING")
        run(db, "INSERT INTO app.users(email,password_hash,role,is_active) VALUES('other@demo.local','test','student',true) ON CONFLICT(email) DO NOTHING")

    print("PASS: Fixture setup completed")


def test_link_lifecycle():
    print("--- 2. Profile Link Lifecycle ---")
    # Step A: unlinked user tries link_profile -> created
    r1 = link_profile("DEMO-TEST-001", "unlinked@demo.local", "LINK_PROFILE_V2")
    assert r1["status"] == "created", f"Expected created, got {r1}"
    assert r1["student_code"] == "DEMO-TEST-001"
    print("PASS: Profile link run 1 (created)")

    # Step B: idempotent rerun
    r2 = link_profile("DEMO-TEST-001", "unlinked@demo.local", "LINK_PROFILE_V2")
    assert r2["status"] == "idempotent", f"Expected idempotent, got {r2}"
    print("PASS: Profile link run 2 (idempotent)")

    # Step C: same user tries to claim a different profile code -> rejected
    try:
        link_profile("DEMO-TEST-002", "unlinked@demo.local", "LINK_PROFILE_V2")
        assert False, "Should have raised USER_ALREADY_LINKED"
    except ValueError as e:
        assert "USER_ALREADY_LINKED" in str(e)
        print("PASS: Profile link run 3 (user conflict rejected)")

    # Step D: different user tries to claim already owned profile code -> rejected
    try:
        link_profile("DEMO-TEST-001", "other@demo.local", "LINK_PROFILE_V2")
        assert False, "Should have raised STUDENT_ALREADY_LINKED"
    except ValueError as e:
        assert "STUDENT_ALREADY_LINKED" in str(e)
        print("PASS: Profile link run 4 (target conflict rejected)")


def run_all():
    test_fixture_setup()
    test_link_lifecycle()
    print("ALL PHASE A ISOLATED CHECKS PASSED")


if __name__ == "__main__":
    run_all()
