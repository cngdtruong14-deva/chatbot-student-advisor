"""Explicit, idempotent DEMO seed. Local prompt; never prints passwords."""
import argparse
import getpass
from app.security import password_hash
from app.store import transaction, one, run


def seed(password):
    encoded = password_hash(password)
    with transaction() as db:
        run(db, """INSERT INTO app.grading_policies(code,version,status,rules)
          VALUES('DEMO-1','1','demo',CAST(:rules AS jsonb)) ON CONFLICT DO NOTHING""",
            rules='{"source":"approved DP01-DP17","synthetic":true}')
        policy = one(db, "SELECT id FROM app.grading_policies WHERE code='DEMO-1' AND version='1'")
        run(db, """INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status)
          VALUES('DEMO-CS','1','CNTT mô phỏng',126,:id,'demo') ON CONFLICT DO NOTHING""", id=policy["id"])
        curriculum = one(db, "SELECT id FROM app.curricula WHERE code='DEMO-CS' AND version='1'")
        for term in range(1, 8):
            run(db, "INSERT INTO app.semesters(code,start_date,end_date) VALUES(:code,:start,:end) ON CONFLICT DO NOTHING",
                code=f"DEMO-T{term}", start=f"{2026+term}-01-01", end=f"{2026+term}-06-30")
        semester = one(db, "SELECT id FROM app.semesters WHERE code='DEMO-T5'")
        for n in range(1, 43):
            code = f"DEMO-C{n:02}"
            run(db, "INSERT INTO app.courses(code,title,domain_id) VALUES(:code,:title,'demo_academic') ON CONFLICT DO NOTHING", code=code, title=f"Học phần mô phỏng {n:02}")
            course = one(db, "SELECT id FROM app.courses WHERE code=:code", code=code)
            run(db, "INSERT INTO app.curriculum_courses(curriculum_id,course_id,credits,recommended_term_no) VALUES(:cid,:course,3,:term) ON CONFLICT DO NOTHING", cid=curriculum["id"], course=course["id"], term=(n-1)//6+1)
            run(db, "INSERT INTO app.course_offerings(course_id,semester_id,policy_id,credits,is_open) VALUES(:course,:semester,:policy,3,true) ON CONFLICT DO NOTHING", course=course["id"], semester=semester["id"], policy=policy["id"])
            offering = one(db, "SELECT id FROM app.course_offerings WHERE course_id=:course AND semester_id=:semester", course=course["id"], semester=semester["id"])
            for component, weight in [("attendance", ".1"), ("assignment", ".2"), ("midterm", ".3"), ("final", ".4")]:
                run(db, "INSERT INTO app.assessment_components(offering_id,code,weight) VALUES(:id,:code,:weight) ON CONFLICT DO NOTHING", id=offering["id"], code=component, weight=weight)
        for email, role in [("student@demo.local", "student"), ("student2@demo.local", "student"), ("advisor@demo.local", "advisor"), ("admin@demo.local", "admin")]:
            run(db, "INSERT INTO app.users(email,password_hash,role) VALUES(:email,:password,:role) ON CONFLICT DO NOTHING", email=email, password=encoded, role=role)
            user = one(db, "SELECT id FROM app.users WHERE email=:email", email=email)
            if role != "student":
                continue
            run(db, """INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,domain_id,data_origin)
              VALUES(:uid,:code,:name,:cid,'DEMO-2026','demo_academic','synthetic') ON CONFLICT DO NOTHING""",
                uid=user["id"], code="DEMO-001" if email.startswith("student@") else "DEMO-002", name="Sinh viên mô phỏng", cid=curriculum["id"])
            student = one(db, "SELECT id FROM app.students WHERE user_id=:id", id=user["id"])
            for n in range(1, 26):
                offering = one(db, "SELECT o.id,o.course_id FROM app.course_offerings o JOIN app.courses c ON c.id=o.course_id WHERE c.code=:code", code=f"DEMO-C{n:02}")
                run(db, """INSERT INTO app.enrollments(student_id,offering_id,course_id,attempt_no,status,final_score,finalized_at)
                  VALUES(:sid,:oid,:cid,1,:status,:score,:finalized) ON CONFLICT DO NOTHING""", sid=student["id"], oid=offering["id"], cid=offering["course_id"], status="graded" if n <= 24 else "pending", score="7.4" if n <= 24 else None, finalized="2026-09-06T00:00:00Z" if n <= 24 else None)
                if n == 25:
                    enrollment = one(db, "SELECT id FROM app.enrollments WHERE student_id=:sid AND offering_id=:oid", sid=student["id"], oid=offering["id"])
                    for code, score in [("attendance", 9), ("assignment", 8), ("midterm", 7)]:
                        component = one(db, "SELECT id FROM app.assessment_components WHERE offering_id=:id AND code=:code", id=offering["id"], code=code)
                        run(db, "INSERT INTO app.grade_components(enrollment_id,component_id,score) VALUES(:eid,:cid,:score) ON CONFLICT DO NOTHING", eid=enrollment["id"], cid=component["id"], score=score)
        run(db, """INSERT INTO app.advisor_assignments(advisor_user_id,student_id)
          SELECT u.id,s.id FROM app.users u CROSS JOIN app.students s
          WHERE u.email='advisor@demo.local' AND s.student_code='DEMO-001' ON CONFLICT DO NOTHING""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True)
    parser.parse_args()
    seed(getpass.getpass("Mật khẩu DEMO local (12–256 ký tự): "))
    print("DEMO seed complete. Existing passwords preserved.")
