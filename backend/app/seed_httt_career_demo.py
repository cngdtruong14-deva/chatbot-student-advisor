"""Opt-in, idempotent HTTT demo-grade seed for career skill-gap demonstrations."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

CONFIRM_PHRASE = "SEED_HTTT_CAREER_DEMO"
DEFAULT_EMAIL = "student@demo.local"
DATA_PATH = Path(__file__).with_name("resources") / "sample_csv" / "htt_demo_grades.csv"
SEMESTERS = {
    "HTTT-DEMO-1": ("2025-01-06", "2025-05-31"),
    "HTTT-DEMO-2": ("2025-08-04", "2025-12-20"),
}


def load_rows() -> list[dict]:
    with DATA_PATH.open(encoding="utf-8-sig", newline="") as stream:
        result = list(csv.DictReader(stream))
    if len(result) != 17 or set(result[0]) != {"semester_code", "course_code", "attempt_no", "final_score"}:
        raise RuntimeError("HTTT_CAREER_DEMO_FIXTURE_INVALID")
    return result


def seed_on_connection(db, email: str = DEFAULT_EMAIL, *, dry_run: bool = True) -> dict:
    """Seed using a caller-owned transaction (used by isolated verification)."""
    from app.store import one, rows, run
    fixture = load_rows()
    student = one(db, """SELECT s.id,s.academic_revision,c.id AS curriculum_id,c.code AS curriculum_code,
          c.policy_id FROM app.users u JOIN app.students s ON s.user_id=u.id
          JOIN app.curricula c ON c.id=s.curriculum_id WHERE lower(u.email)=lower(:email)""", email=email)
    if not student:
        raise RuntimeError("STUDENT_PROFILE_NOT_FOUND")
    if student["curriculum_code"] != "HTTT-UTT":
        raise RuntimeError("STUDENT_NOT_LINKED_TO_HTTT_UTT")
    known = {row["course_code"] for row in fixture}
    courses = {row["code"]: row for row in rows(db, """
          SELECT c.id,c.code,cc.credits FROM app.courses c
          JOIN app.curriculum_courses cc ON cc.course_id=c.id
          WHERE cc.curriculum_id=:curriculum AND c.code = ANY(:codes)""",
      curriculum=student["curriculum_id"], codes=list(known))}
    if set(courses) != known:
        raise RuntimeError("HTTT_DEMO_COURSE_NOT_IN_CURRICULUM")
    existing = one(db, """SELECT count(*) AS count FROM app.enrollments
          WHERE student_id=:student AND course_id=ANY(:courses)""",
      student=student["id"], courses=[row["id"] for row in courses.values()])
    preview = {"student_email": email, "rows": len(fixture), "existing_rows": int(existing["count"]),
               "would_insert_at_most": len(fixture), "dry_run": dry_run}
    if dry_run:
        return preview
    inserted = 0
    for code, (start, end) in SEMESTERS.items():
        run(db, """INSERT INTO app.semesters(code,start_date,end_date) VALUES(:code,:start,:end)
              ON CONFLICT(code) DO NOTHING""", code=code, start=start, end=end)
    semester_ids = {code: one(db, "SELECT id FROM app.semesters WHERE code=:code", code=code)["id"] for code in SEMESTERS}
    for item in fixture:
        course = courses[item["course_code"]]
        run(db, """INSERT INTO app.course_offerings(course_id,semester_id,policy_id,credits,is_open)
              VALUES(:course,:semester,:policy,:credits,false) ON CONFLICT(course_id,semester_id) DO NOTHING""",
          course=course["id"], semester=semester_ids[item["semester_code"]],
          policy=student["policy_id"], credits=course["credits"])
        offering = one(db, "SELECT id FROM app.course_offerings WHERE course_id=:course AND semester_id=:semester",
                       course=course["id"], semester=semester_ids[item["semester_code"]])
        result = run(db, """INSERT INTO app.enrollments(
              student_id,offering_id,course_id,attempt_no,status,final_score,recognized,minimums_met,finalized_at)
              VALUES(:student,:offering,:course,:attempt,'graded',:score,false,true,now())
              ON CONFLICT DO NOTHING""", student=student["id"], offering=offering["id"],
          course=course["id"], attempt=int(item["attempt_no"]), score=item["final_score"])
        inserted += result.rowcount
    if inserted:
        run(db, "UPDATE app.students SET academic_revision=academic_revision+1,updated_at=now() WHERE id=:id",
            id=student["id"])
    run(db, """INSERT INTO app.audit_logs(actor_id,action,entity_type,entity_id,status,request_id)
          SELECT id,'seed_httt_career_demo','student',:student,'completed',:request
          FROM app.users WHERE lower(email)=lower(:email)""", student=str(student["id"]),
      request="seed-httt-career-demo", email=email)
    return {**preview, "dry_run": False, "inserted_rows": inserted,
            "skipped_existing_rows": len(fixture) - inserted}


def seed(email: str = DEFAULT_EMAIL, *, dry_run: bool = True) -> dict:
    from app.store import transaction
    with transaction() as db:
        return seed_on_connection(db, email, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.confirm not in (None, CONFIRM_PHRASE):
        raise SystemExit("Invalid confirmation phrase")
    print(seed(args.email, dry_run=args.confirm != CONFIRM_PHRASE))


if __name__ == "__main__":
    main()
