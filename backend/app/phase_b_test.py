"""Phase B verification runner on isolated DB.

Gates:
1. Document lifecycle: register (pending) -> ingest (ready + chunks) -> activate (active).
2. Corpus search access control: demo_academic open, utt_test restricted.
3. Advisor assignments: admin-only writes, advisor sees only assigned students.
4. Corpus scope isolation: utt_test metadata and chunk partitioning.
"""
import os
from datetime import date

from app.test_safety import require_test_environment

require_test_environment()

from app.store import one, run, transaction
from app.knowledge import DocumentInput, accessible_chunks, activate, ingest, register_document


def lazy_import_api():
    """Lazy import api module to avoid advisor_core dependency during module load."""
    from app.api import APIError, Assignment, assign, assigned_students, allow_corpus
    return APIError, Assignment, assign, assigned_students, allow_corpus


def test_fixture_setup():
    print("--- 0. Fixture Setup ---")
    with transaction() as db:
        run(db, "INSERT INTO app.grading_policies(code,version,status,rules) VALUES('DEMO-1','1','demo','{}') ON CONFLICT(code,version) DO NOTHING")
        policy = one(db, "SELECT id FROM app.grading_policies WHERE code='DEMO-1'")

        run(db, """INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status)
          VALUES('DEMO-CS','1','Test',126,:pid,'demo') ON CONFLICT(code,version) DO NOTHING""", pid=policy["id"])
        curriculum = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS'")

        run(db, "INSERT INTO app.cohorts(code,curriculum_id) VALUES('DEMO-2026',:cid) ON CONFLICT(code) DO NOTHING", cid=curriculum["id"])
        cohort = one(db, "SELECT id FROM app.cohorts WHERE code='DEMO-2026'")

        for email, role in (("admin_b@demo.local", "admin"), ("advisor_b@demo.local", "advisor"),
                            ("student_demo_b@demo.local", "student"), ("student_real_b@demo.local", "student"),
                            ("student_unlinked_b@demo.local", "student")):
            run(db, """INSERT INTO app.users(email,password_hash,role,is_active) VALUES(:email,'test',:role,true)
              ON CONFLICT(email) DO NOTHING""", email=email, role=role)

        demo_user = one(db, "SELECT id FROM app.users WHERE email='student_demo_b@demo.local'")
        real_user = one(db, "SELECT id FROM app.users WHERE email='student_real_b@demo.local'")

        run(db, """INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
          VALUES(:uid,'STU-DEMO-B','Demo Student B',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')
          ON CONFLICT(domain_id,student_code) DO NOTHING""", cid=curriculum["id"], cohid=cohort["id"], uid=demo_user["id"])
    print("PASS: Fixture setup completed")


DOCUMENT_BODY = """# Quy chế đào tạo demo B

## Điều 1: Phạm vi áp dụng
Văn bản mô phỏng quy định đào tạo theo học chế tín chỉ cho sinh viên demo.

## Điều 2: Điểm đánh giá
Điểm thành phần và điểm thi kết thúc học phần dùng thang điểm 10; điểm đạt tối thiểu là 4.
"""


def test_gate_1_document_lifecycle():
    print("--- 1. Gate 1: Document Lifecycle ---")
    admin = actor("admin_b@demo.local")
    body = DocumentInput(title="Quy chế đào tạo demo B", document_type="policy",
                         source="internal:docs/qc_demo_b.md", version="QC-B-1.0", content=DOCUMENT_BODY,
                         valid_from=date(2026, 1, 1), valid_until=date(2027, 12, 31), corpus_scope="demo_academic")
    registered = register_document(body, admin["id"])
    version_id = registered["id"]
    assert registered["status"] == "pending", f"Expected pending, got {registered['status']}"
    assert registered["scope_key"] == "demo_academic"
    assert registered["data_origin"] == "synthetic"
    assert registered["review_state"] == "approved_demo"
    print("PASS: Document registered in pending state")

    # Pending versions have no chunks and cannot change active corpus visibility.
    assert not any(ch["version_id"] == str(version_id) for ch in accessible_chunks(corpus_scope="demo_academic"))
    print("PASS: Pending document does not change active demo_academic corpus")

    try:
        activate(version_id)
        assert False, "Activation must require ingest/ready state"
    except ValueError as exc:
        assert str(exc) == "DOCUMENT_NOT_READY"
    print("PASS: Activation rejected until ingest reaches ready state")

    replay = register_document(body, admin["id"])
    assert replay["replayed"] is True and replay["id"] == version_id
    print("PASS: Duplicate registration replayed without new version")

    ingested = ingest(version_id)
    assert ingested["status"] == "ready", f"Expected ready, got {ingested['status']}"
    assert ingested["chunks"] > 0, f"Expected chunks, got {ingested['chunks']}"
    with transaction() as db:
        stored = one(db, "SELECT count(*) AS total FROM app.chunks WHERE version_id=:id", id=version_id)
    assert stored["total"] == ingested["chunks"]
    print(f"PASS: Document ingested with {ingested['chunks']} chunks")

    assert activate(version_id)["status"] == "active"
    with transaction() as db:
        assert one(db, "SELECT status FROM app.document_versions WHERE id=:id", id=version_id)["status"] == "active"
    print("PASS: Document activated")

    audit = None
    with transaction() as db:
        audit = one(db, "SELECT action,status FROM app.audit_logs WHERE entity_id=:id AND action='activate_document'", id=str(version_id))
    assert audit and audit["status"] == "active"
    print("PASS: Activation audit log written")


def test_gate_2_search_access_control():
    print("--- 2. Gate 2: Corpus Search Access Control ---")
    APIError, _, _, _, allow_corpus = lazy_import_api()
    admin, advisor = actor("admin_b@demo.local"), actor("advisor_b@demo.local")
    demo_student, real_student = actor("student_demo_b@demo.local"), actor("student_real_b@demo.local")
    unlinked_student = actor("student_unlinked_b@demo.local")

    for user in (admin, advisor, demo_student, real_student, unlinked_student):
        allow_corpus(user, "demo_academic")
    print("PASS: demo_academic scope open to every role")

    allow_corpus(admin, "utt_test")
    print("PASS: utt_test scope allowed for admin")

    for user, label in ((demo_student, "linked student"), (real_student, "student"), (unlinked_student, "unlinked student")):
        allow_corpus(user, "utt_corpus")
        print(f"PASS: utt_corpus general access allowed for {label}")

    try:
        allow_corpus(unlinked_student, "utt_test")
        assert False, "Unlinked student must not access utt_test"
    except APIError as exc:
        assert exc.code == "FORBIDDEN" and exc.status == 403
    print("PASS: utt_test scope rejected for unlinked student (FORBIDDEN 403)")

    for user, label in ((demo_student, "linked student"), (real_student, "student"), (advisor, "advisor")):
        try:
            allow_corpus(user, "utt_test")
            assert False, f"utt_test must be rejected for {label}"
        except APIError as exc:
            assert exc.code == "FORBIDDEN" and exc.status == 403, f"Expected FORBIDDEN 403, got {exc.code} {exc.status}"
        print(f"PASS: utt_test scope rejected for {label} (FORBIDDEN 403)")



def test_gate_3_advisor_assignments():
    print("--- 3. Gate 3: Advisor Assignments & Access Control ---")
    APIError, Assignment, assign, assigned_students, _ = lazy_import_api()
    admin, advisor, non_advisor = actor("admin_b@demo.local"), actor("advisor_b@demo.local"), actor("student_demo_b@demo.local")
    with transaction() as db:
        demo_student = one(db, "SELECT id,student_code FROM app.students WHERE student_code='STU-DEMO-B'")
        real_user = one(db, "SELECT id FROM app.users WHERE email='student_real_b@demo.local'")
        curriculum = one(db, "SELECT curriculum_id,cohort_id FROM app.students WHERE student_code='STU-DEMO-B'")
        run(db, """INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
          VALUES(:uid,'STU-REAL-B','Real Student B',:cid,'DEMO-2026',:cohid,'demo_academic','synthetic')
          ON CONFLICT(domain_id,student_code) DO NOTHING""", uid=real_user["id"], cid=curriculum["curriculum_id"], cohid=curriculum["cohort_id"])
        real_student = one(db, "SELECT id,student_code FROM app.students WHERE student_code='STU-REAL-B'")

    for non_admin, label in ((advisor, "advisor"), (non_advisor, "student")):
        try:
            assign(Assignment(advisor_user_id=advisor["id"], student_id=demo_student["id"]), user=non_admin)
            assert False, f"Non-admin {label} must not assign"
        except APIError as exc:
            assert exc.code == "FORBIDDEN" and exc.status == 403
        print(f"PASS: Non-admin {label} rejected from assign route (FORBIDDEN 403)")

    try:
        assign(Assignment(advisor_user_id=non_advisor["id"], student_id=demo_student["id"]), user=admin)
        assert False, "Cannot assign non-advisor role as advisor"
    except APIError as exc:
        assert exc.code == "INVALID_ADVISOR"
    print("PASS: Non-advisor user rejected (INVALID_ADVISOR)")

    result = assign(Assignment(advisor_user_id=advisor["id"], student_id=demo_student["id"]), user=admin)
    assert result["data"]["assigned"] is True
    print("PASS: Admin assigned advisor to STU-DEMO-B")

    advisor_view = assigned_students(user=advisor)
    advisor_codes = [s["student_code"] for s in advisor_view["data"]["items"]]
    assert "STU-DEMO-B" in advisor_codes and "STU-REAL-B" not in advisor_codes, f"Advisor should see only assigned students, got {advisor_codes}"
    print(f"PASS: Advisor sees only assigned student: {advisor_codes}")

    admin_view = assigned_students(user=admin)
    admin_codes = [s["student_code"] for s in admin_view["data"]["items"]]
    assert "STU-DEMO-B" in admin_codes and "STU-REAL-B" in admin_codes
    print("PASS: Admin sees all students")


def test_gate_4_corpus_scope_isolation():
    print("--- 4. Gate 4: Corpus Scope Isolation ---")
    admin = actor("admin_b@demo.local")
    utt_doc = DocumentInput(title="Tài liệu UTT khảo sát B", document_type="guide",
                            source="upload:utt_guide_b.md", version="UTT-B-1.0",
                            content="Hướng dẫn đăng ký học phần thí điểm trường UTT.",
                            valid_from=date(2026, 1, 1), valid_until=date(2027, 1, 1),
                            corpus_scope="utt_test")
    reg_utt = register_document(utt_doc, admin["id"])
    assert reg_utt["scope_key"] == "utt_test"
    assert reg_utt["data_origin"] == "user_provided_institutional_document"
    assert reg_utt["review_state"] == "test_only"
    print("PASS: utt_test document registered with isolated origin and test_only review state")

    utt_ingested = ingest(reg_utt["id"])
    assert utt_ingested["status"] == "ready" and utt_ingested["chunks"] > 0
    assert activate(reg_utt["id"])["status"] == "active"

    demo_chunks = accessible_chunks(corpus_scope="demo_academic")
    utt_chunks = accessible_chunks(corpus_scope="utt_test")
    assert demo_chunks and utt_chunks, "Both active scopes must expose their own chunks"
    assert all(ch["scope_key"] == "demo_academic" for ch in demo_chunks)
    assert all(ch["scope_key"] == "utt_test" for ch in utt_chunks)
    assert not ({ch["chunk_id"] for ch in demo_chunks} & {ch["chunk_id"] for ch in utt_chunks})
    print(f"PASS: Bidirectional scope isolation verified ({len(demo_chunks)} demo_academic, {len(utt_chunks)} utt_test chunks)")


def actor(email):
    with transaction() as db:
        return one(db, "SELECT id,email,role FROM app.users WHERE email=:email", email=email)


def run_all():
    test_fixture_setup()
    test_gate_1_document_lifecycle()
    test_gate_2_search_access_control()
    test_gate_3_advisor_assignments()
    test_gate_4_corpus_scope_isolation()
    print("\n" + "=" * 50)
    print("ALL 4 PHASE B GATES PASSED SUCCESSFULLY")
    print("=" * 50)


if __name__ == "__main__":
    run_all()
