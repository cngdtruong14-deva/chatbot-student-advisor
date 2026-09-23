"""Bounded catalog and enrollment CSV imports. All-or-nothing transactions with dry-run."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from uuid import UUID
from fastapi import Request

from app import academic as ac
from app.api import APIError, Actor, envelope, require_role, router
from app.store import transaction, one, rows, run



SUPPORTED_IMPORTS = {
    "curricula", "cohorts", "semesters",
    "academic",
    "enrollments",
    "students",
    "courses",
    "curriculum_courses",
    "offerings",
    "prerequisites",
    "grade_components",
    "grade_component_scores",
}

TEMPLATES = {
    "academic": "student_code,course_code,semester_code,attempt_no,status,final_score,policy_version,data_origin\nDEMO-003,DEMO-C43,DEMO-T5,1,pending,,DEMO-1,synthetic\n",
    "curricula": "code,version,major,total_required_credits,policy_code,policy_version\nDEMO-CS,1,CNTT,126,DEMO-1,1\n",
    "cohorts": "code,curriculum_code,curriculum_version\nDEMO-2026,DEMO-CS,1\n",
    "semesters": "code,start_date,end_date\nDEMO-T5,2026-09-01,2026-12-31\n",
    "students": "student_code,full_name,account_email,cohort,curriculum_code,curriculum_version\nDEMO-003,Sinh vien demo,student3@demo.local,DEMO-2026,DEMO-CS,1\n",
    "courses": "code,title\nDEMO-C43,Hoc phan mo phong\n",
    "curriculum_courses": "curriculum_code,curriculum_version,course_code,credits,required,recommended_term_no\nDEMO-CS,1,DEMO-C43,3,true,8\n",
    "prerequisites": "curriculum_code,curriculum_version,course_code,prerequisite_course_code,min_grade_point\nDEMO-CS,1,DEMO-C43,DEMO-C42,1.6\n",
    "offerings": "course_code,semester_code,credits,is_open,policy_code,policy_version\nDEMO-C43,DEMO-T5,3,true,DEMO-1,1\n",
    "grade_components": "course_code,semester_code,component_code,weight,minimum_required\nDEMO-C43,DEMO-T5,FINAL,1.0,0\n",
    "enrollments": "student_code,course_code,semester_code,attempt_no,status,final_score,policy_version,data_origin\nDEMO-003,DEMO-C43,DEMO-T5,1,pending,,DEMO-1,synthetic\n",
    "grade_component_scores": "student_code,course_code,semester_code,component_code,score\nDEMO-003,DEMO-C43,DEMO-T5,FINAL,8.0\n",
}


def _read_csv(content: bytes, required_fields: set[str]) -> list[dict]:
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        actual = set(reader.fieldnames or [])
        if not required_fields.issubset(actual):
            raise ValueError(f"Missing required fields: {required_fields - actual}")
        records = list(reader)
        if not 1 <= len(records) <= 1000:
            raise ValueError("Records count must be between 1 and 1000")
        return records
    except Exception as exc:
        raise APIError("INVALID_CSV", 422, str(exc)) from exc


def _error(line: int, code: str, field: str | None = None):
    """Stable, non-secret row error shape used by preview and automated clients."""
    result = {"line": line, "code": code}
    if field:
        result["field"] = field
    return result


def _outcome(db, actor_id, import_type, digest, dry_run, errors, record_count, writes=0):
    """Persist provenance for every validation outcome without touching academics."""
    status = "dry_invalid" if dry_run and errors else "dry_validated" if dry_run else "invalid" if errors else "completed"
    job = one(db, """INSERT INTO app.import_jobs(actor_id,import_type,input_hash,status,errors_json)
        VALUES(:actor,:type,:hash,:status,CAST(:errors AS jsonb))
        ON CONFLICT(actor_id,import_type,input_hash) DO UPDATE SET
        status=CASE WHEN app.import_jobs.status='completed' THEN app.import_jobs.status ELSE excluded.status END,
        errors_json=CASE WHEN app.import_jobs.status='completed' THEN app.import_jobs.errors_json ELSE excluded.errors_json END
        RETURNING id,status""", actor=actor_id, type=import_type, hash=digest, status=status, errors=json.dumps(errors))
    if not dry_run:
        run(db, """INSERT INTO app.audit_logs(actor_id,action,entity_type,entity_id,status,request_id)
            VALUES(:actor,'import',:type,:job,:status,:job)""", actor=actor_id, type=import_type, job=str(job["id"]), status=status)
    return envelope({"job_id": job["id"], "dry_run": dry_run, "status": "invalid" if errors else "validated" if dry_run else "completed",
                     "errors": errors, "rows": record_count, "writes": writes,
                     "academic_writes": writes if import_type == 'enrollments' else 0})


@router.get("/admin/imports/templates/{import_type}")
def import_template(import_type: str, user: Actor):
    require_role(user, "admin")
    if import_type not in TEMPLATES:
        raise APIError("UNSUPPORTED_IMPORT_TYPE", 404)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(TEMPLATES[import_type], media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{import_type}.csv"'})


@router.get("/admin/imports/history")
def import_history(user: Actor, limit: int = 50):
    require_role(user, "admin")
    if not 1 <= limit <= 100:
        raise APIError("INVALID_PAGE")
    with transaction() as db:
        return envelope(rows(db, """SELECT id,import_type,input_hash,status,errors_json,created_at
            FROM app.import_jobs WHERE actor_id=:actor ORDER BY created_at DESC LIMIT :limit""",
            actor=user["id"], limit=limit))


@router.post("/admin/imports/academic")
@router.post("/admin/imports/{import_type}")
async def import_csv_handler(request: Request, user: Actor, import_type: str = "academic", dry_run: bool = True):
    require_role(user, "admin")
    if import_type not in SUPPORTED_IMPORTS:
        raise APIError("UNSUPPORTED_IMPORT_TYPE", 404)
    if request.headers.get("content-type", "").split(";")[0] != "text/csv":
        raise APIError("INVALID_CONTENT_TYPE", 415, "Gửi CSV UTF-8, Content-Type text/csv")

    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > 512_000:
            raise APIError("BATCH_TOO_LARGE", 413)

    digest = hashlib.sha256(content).hexdigest()
    normalized_type = "enrollments" if import_type == "academic" else import_type

    with transaction() as db:
        run(db, "SELECT pg_advisory_xact_lock(732451)")
        previous = one(db, "SELECT id,status FROM app.import_jobs WHERE actor_id=:uid AND import_type=:type AND input_hash=:hash",
                       uid=user["id"], type=normalized_type, hash=digest)
        if previous and not dry_run and previous["status"] == "completed":
            return envelope({"job_id": previous["id"], "status": previous["status"], "idempotent_replay": True})

        errors, writes_count = [], 0

        # Parent catalogs are deliberately separate: student import never provisions
        # a login account, and every child resolves only published business codes.
        if normalized_type == "curricula":
            records = _read_csv(content, {"code", "version", "major", "total_required_credits", "policy_code", "policy_version"})
            validated, seen = [], set()
            for line, row in enumerate(records, 2):
                try:
                    code, version, major = row["code"].strip(), row["version"].strip(), row["major"].strip()
                    key = (code, version)
                    credits = ac.decimal(row["total_required_credits"], 0.5, 1000)
                    policy = one(db, "SELECT id FROM app.grading_policies WHERE code=:code AND version=:version", code=row["policy_code"].strip(), version=row["policy_version"].strip())
                    if not code or not version or not major or key in seen: raise ValueError("DUPLICATE_BUSINESS_KEY")
                    if not policy: raise LookupError("UNRESOLVED_POLICY")
                    seen.add(key); validated.append((code, version, major, credits, policy["id"]))
                except LookupError as exc: errors.append(_error(line, str(exc)))
                except Exception: errors.append(_error(line, "INVALID_CURRICULUM"))
            if errors or dry_run: return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))
            for code, version, major, credits, policy_id in validated:
                run(db, """INSERT INTO app.curricula(code,version,major,total_required_credits,policy_id,status)
                    VALUES(:code,:version,:major,:credits,:policy,'demo') ON CONFLICT(code,version) DO UPDATE
                    SET major=excluded.major,total_required_credits=excluded.total_required_credits,policy_id=excluded.policy_id""",
                    code=code, version=version, major=major, credits=credits, policy=policy_id); writes_count += 1

        elif normalized_type == "cohorts":
            records = _read_csv(content, {"code", "curriculum_code", "curriculum_version"})
            validated, seen = [], set()
            for line, row in enumerate(records, 2):
                code = (row["code"] or "").strip(); key = code
                curriculum = one(db, "SELECT id FROM app.curricula WHERE code=:code AND version=:version", code=(row["curriculum_code"] or "").strip(), version=(row["curriculum_version"] or "").strip())
                if not code: errors.append(_error(line, "INVALID_COHORT", "code"))
                elif key in seen: errors.append(_error(line, "DUPLICATE_BUSINESS_KEY", "code"))
                elif not curriculum: errors.append(_error(line, "UNRESOLVED_CURRICULUM"))
                else: seen.add(key); validated.append((code, curriculum["id"]))
            if errors or dry_run: return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))
            for code, curriculum_id in validated:
                run(db, """INSERT INTO app.cohorts(code,curriculum_id) VALUES(:code,:curriculum)
                  ON CONFLICT(code) DO UPDATE SET curriculum_id=excluded.curriculum_id""", code=code, curriculum=curriculum_id); writes_count += 1

        elif normalized_type == "semesters":
            records = _read_csv(content, {"code", "start_date", "end_date"})
            validated, seen = [], set()
            from datetime import date
            for line, row in enumerate(records, 2):
                try:
                    code = row["code"].strip(); start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
                    if not code or code in seen: raise ValueError()
                    if end < start: raise ValueError()
                    seen.add(code); validated.append((code, start, end))
                except Exception: errors.append(_error(line, "INVALID_SEMESTER"))
            if errors or dry_run: return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))
            for code, start, end in validated:
                run(db, """INSERT INTO app.semesters(code,start_date,end_date) VALUES(:code,:start,:end)
                  ON CONFLICT(code) DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date""", code=code, start=start, end=end); writes_count += 1

        # -------------------------------------------------------------
        # 1. ENROLLMENTS
        # -------------------------------------------------------------
        if normalized_type == "enrollments":
            fields = {"student_code", "course_code", "semester_code", "attempt_no", "status", "final_score", "policy_version", "data_origin"}
            records = _read_csv(content, fields)
            validated, keys = [], set()
            for index, row in enumerate(records, start=2):
                try:
                    if None in row or row["policy_version"] != "DEMO-1" or row["data_origin"] != "synthetic" or row["status"] not in {"graded", "pending", "incomplete", "withdrawn"}:
                        raise ValueError()
                    attempt = int(row["attempt_no"])
                    if attempt <= 0:
                        raise ValueError()
                    score = ac.decimal(row["final_score"], 0, 10) if row["status"] == "graded" else None
                    if row["status"] != "graded" and row["final_score"]:
                        raise ValueError()
                    student = one(db, "SELECT id FROM app.students WHERE student_code=:code AND domain_id='demo_academic' FOR UPDATE", code=row["student_code"])
                    offering = one(db, """SELECT o.id,o.course_id FROM app.course_offerings o JOIN app.courses c ON c.id=o.course_id
                      JOIN app.semesters s ON s.id=o.semester_id WHERE c.code=:course AND s.code=:semester""", course=row["course_code"], semester=row["semester_code"])
                    if not student or not offering:
                        raise ValueError()
                    key = (str(student["id"]), str(offering["id"]))
                    if key in keys:
                        raise ValueError()
                    keys.add(key)
                    current = one(db, "SELECT * FROM app.enrollments WHERE student_id=:sid AND offering_id=:oid", sid=student["id"], oid=offering["id"])
                    conflict = one(db, "SELECT id FROM app.enrollments WHERE student_id=:sid AND course_id=:cid AND attempt_no=:attempt AND offering_id<>:oid",
                                   sid=student["id"], cid=offering["course_id"], attempt=attempt, oid=offering["id"])
                    if conflict or current and current["attempt_no"] != attempt:
                        raise ValueError()
                    if current and current["finalized_at"] and (current["status"] != row["status"] or current["final_score"] != score):
                        raise RuntimeError("FINALIZED_RECORD_CONFLICT")
                    if row["status"] == "graded" and current:
                        components = one(db, "SELECT count(*) AS count FROM app.grade_components WHERE enrollment_id=:id", id=current["id"])["count"]
                        if components:
                            raise ValueError()
                    validated.append((student, offering, attempt, row["status"], score, current))
                except RuntimeError as exc:
                    errors.append(_error(index, str(exc)))
                except (ValueError, TypeError, KeyError):
                    errors.append(_error(index, "INVALID_ENROLLMENT"))

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            changed = set()
            for student, offering, attempt, status, score, current in validated:
                if current and current["status"] == status and current["final_score"] == score:
                    continue
                run(db, """INSERT INTO app.enrollments(student_id,offering_id,course_id,attempt_no,status,final_score,finalized_at)
                  VALUES(:sid,:oid,:cid,:attempt,:status,:score,CASE WHEN :status='graded' THEN now() END)
                  ON CONFLICT(student_id,offering_id) DO UPDATE SET status=excluded.status,final_score=excluded.final_score,finalized_at=excluded.finalized_at""",
                    sid=student["id"], oid=offering["id"], cid=offering["course_id"], attempt=attempt, status=status, score=score)
                changed.add(student["id"])
                writes_count += 1
            for sid in changed:
                run(db, "UPDATE app.students SET academic_revision=academic_revision+1,updated_at=now() WHERE id=:id", id=sid)

        # -------------------------------------------------------------
        # 2. COURSES
        # -------------------------------------------------------------
        elif normalized_type == "courses":
            fields = {"code", "title"}
            records = _read_csv(content, fields)
            validated, seen = [], set()
            for index, row in enumerate(records, start=2):
                try:
                    code = (row["code"] or "").strip()
                    title = (row["title"] or "").strip()
                    if not code or not title or code in seen:
                        raise ValueError()
                    seen.add(code)
                    validated.append((code, title))
                except (ValueError, KeyError):
                    errors.append({"line": index, "code": "INVALID_ROW"})

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for code, title in validated:
                run(db, """INSERT INTO app.courses(code,title,domain_id) VALUES(:code,:title,'demo_academic')
                  ON CONFLICT(domain_id,code) DO UPDATE SET title=excluded.title""", code=code, title=title)
                writes_count += 1

        # -------------------------------------------------------------
        # 3. STUDENTS
        # -------------------------------------------------------------
        elif normalized_type == "students":
            fields = {"student_code", "full_name", "account_email", "cohort", "curriculum_code", "curriculum_version"}
            records = _read_csv(content, fields)
            validated, seen_codes, seen_emails = [], set(), set()
            for index, row in enumerate(records, start=2):
                try:
                    scode = (row["student_code"] or "").strip()
                    name = (row["full_name"] or "").strip()
                    email = (row["account_email"] or "").strip().lower()
                    cohort = (row["cohort"] or "").strip()
                    ccode = (row["curriculum_code"] or "").strip()
                    if not scode or not name or not email or not cohort or not ccode:
                        raise ValueError()
                    if scode in seen_codes or email in seen_emails:
                        raise ValueError()
                    seen_codes.add(scode)
                    seen_emails.add(email)
                    version = (row["curriculum_version"] or "").strip()
                    curriculum = one(db, "SELECT id FROM app.curricula WHERE code=:code AND version=:version", code=ccode, version=version)
                    cohort_row = one(db, "SELECT id,curriculum_id FROM app.cohorts WHERE code=:code", code=cohort)
                    user_row = one(db, "SELECT id,role FROM app.users WHERE email=:email AND is_active", email=email)
                    if not curriculum:
                        raise LookupError("UNRESOLVED_CURRICULUM")
                    if not cohort_row or cohort_row["curriculum_id"] != curriculum["id"]:
                        raise LookupError("UNRESOLVED_COHORT")
                    # Accounts are provisioned by the explicit admin/auth path only.
                    if not user_row or user_row["role"] != "student":
                        raise LookupError("UNRESOLVED_STUDENT_ACCOUNT")
                    linked = one(db, "SELECT student_code FROM app.students WHERE user_id=:id", id=user_row["id"])
                    if linked and linked["student_code"] != scode:
                        raise LookupError("ACCOUNT_ALREADY_LINKED")
                    existing_student = one(db, "SELECT user_id FROM app.students WHERE domain_id='demo_academic' AND student_code=:code", code=scode)
                    if existing_student and existing_student["user_id"] != user_row["id"]:
                        raise LookupError("STUDENT_ACCOUNT_LINK_CONFLICT")
                    validated.append((scode, name, cohort, curriculum["id"], cohort_row["id"], user_row["id"]))
                except LookupError as exc:
                    errors.append(_error(index, str(exc)))
                except (ValueError, KeyError):
                    errors.append(_error(index, "INVALID_STUDENT"))

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for scode, name, cohort, cur_id, cohort_id, user_id in validated:
                run(db, """INSERT INTO app.students(user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
                  VALUES(:uid,:scode,:name,:cid,:cohort,:cohort_id,'demo_academic','synthetic')
                  ON CONFLICT(domain_id,student_code) DO UPDATE SET full_name=excluded.full_name,curriculum_id=excluded.curriculum_id,cohort=excluded.cohort,cohort_id=:cohort_id,updated_at=now()""",
                    uid=user_id, scode=scode, name=name, cid=cur_id, cohort=cohort, cohort_id=cohort_id)
                writes_count += 1

        # -------------------------------------------------------------
        # 4. CURRICULUM_COURSES
        # -------------------------------------------------------------
        elif normalized_type == "curriculum_courses":
            fields = {"curriculum_code", "curriculum_version", "course_code", "credits", "required", "recommended_term_no"}
            records = _read_csv(content, fields)
            validated, seen = [], set()
            for index, row in enumerate(records, start=2):
                try:
                    cur_code = (row["curriculum_code"] or "").strip()
                    crs_code = (row["course_code"] or "").strip()
                    cr = ac.decimal(row["credits"], 0.5, 30)
                    term_no = int(row["recommended_term_no"])
                    req = row["required"].strip().lower() in {"true", "1", "yes", "t"}
                    if not cur_code or not crs_code or term_no < 1:
                        raise ValueError()
                    cur = one(db, "SELECT id FROM app.curricula WHERE code=:code AND version=:version", code=cur_code, version=(row["curriculum_version"] or "").strip())
                    crs = one(db, "SELECT id FROM app.courses WHERE code=:code AND domain_id='demo_academic'", code=crs_code)
                    if not cur or not crs:
                        raise ValueError()
                    pair = (str(cur["id"]), str(crs["id"]))
                    if pair in seen:
                        raise ValueError()
                    seen.add(pair)
                    validated.append((cur["id"], crs["id"], cr, req, term_no))
                except (ValueError, KeyError):
                    errors.append({"line": index, "code": "INVALID_ROW"})

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for cur_id, crs_id, cr, req, term_no in validated:
                run(db, """INSERT INTO app.curriculum_courses(curriculum_id,course_id,credits,required,recommended_term_no)
                  VALUES(:cid,:crs_id,:cr,:req,:term)
                  ON CONFLICT(curriculum_id,course_id) DO UPDATE SET credits=excluded.credits,required=excluded.required,recommended_term_no=excluded.recommended_term_no""",
                    cid=cur_id, crs_id=crs_id, cr=cr, req=req, term=term_no)
                writes_count += 1

        # -------------------------------------------------------------
        # 5. OFFERINGS
        # -------------------------------------------------------------
        elif normalized_type == "offerings":
            fields = {"course_code", "semester_code", "credits", "is_open", "policy_code", "policy_version"}
            records = _read_csv(content, fields)
            validated, seen = [], set()
            for index, row in enumerate(records, start=2):
                try:
                    crs_code = (row["course_code"] or "").strip()
                    sem_code = (row["semester_code"] or "").strip()
                    cr = ac.decimal(row["credits"], 0.5, 30)
                    is_open = row["is_open"].strip().lower() in {"true", "1", "yes", "t"}
                    crs = one(db, "SELECT id FROM app.courses WHERE code=:code AND domain_id='demo_academic'", code=crs_code)
                    sem = one(db, "SELECT id FROM app.semesters WHERE code=:code", code=sem_code)
                    pol = one(db, "SELECT id FROM app.grading_policies WHERE code=:code AND version=:version", code=(row["policy_code"] or "").strip(), version=(row["policy_version"] or "").strip())
                    if not crs or not sem or not pol:
                        raise ValueError()
                    pair = (str(crs["id"]), str(sem["id"]))
                    if pair in seen:
                        raise ValueError()
                    seen.add(pair)
                    validated.append((crs["id"], sem["id"], pol["id"], cr, is_open))
                except (ValueError, KeyError):
                    errors.append({"line": index, "code": "INVALID_ROW"})

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for crs_id, sem_id, pol_id, cr, is_open in validated:
                run(db, """INSERT INTO app.course_offerings(course_id,semester_id,policy_id,credits,is_open)
                  VALUES(:crs,:sem,:pol,:cr,:open)
                  ON CONFLICT(course_id,semester_id) DO UPDATE SET credits=excluded.credits,is_open=excluded.is_open""",
                    crs=crs_id, sem=sem_id, pol=pol_id, cr=cr, open=is_open)
                writes_count += 1

        # -------------------------------------------------------------
        # 6. PREREQUISITES (WITH DAG CYCLE CHECK)
        # -------------------------------------------------------------
        elif normalized_type == "prerequisites":
            fields = {"curriculum_code", "curriculum_version", "course_code", "prerequisite_course_code", "min_grade_point"}
            records = _read_csv(content, fields)
            validated, seen = [], set()
            curriculum_edges = {}

            for index, row in enumerate(records, start=2):
                try:
                    cur_code = (row["curriculum_code"] or "").strip()
                    crs_code = (row["course_code"] or "").strip()
                    pre_code = (row["prerequisite_course_code"] or "").strip()
                    min_gp = ac.decimal(row["min_grade_point"], 0, 4)
                    if not cur_code or not crs_code or not pre_code or crs_code == pre_code:
                        raise ValueError()
                    cur = one(db, "SELECT id FROM app.curricula WHERE code=:code AND version=:version", code=cur_code, version=(row["curriculum_version"] or "").strip())
                    crs = one(db, "SELECT id FROM app.courses WHERE code=:code AND domain_id='demo_academic'", code=crs_code)
                    pre = one(db, "SELECT id FROM app.courses WHERE code=:code AND domain_id='demo_academic'", code=pre_code)
                    if not cur or not crs or not pre:
                        raise ValueError()
                    key = (str(cur["id"]), str(crs["id"]), str(pre["id"]))
                    if key in seen:
                        raise ValueError()
                    seen.add(key)
                    validated.append((cur["id"], crs["id"], pre["id"], min_gp))
                    curriculum_edges.setdefault(cur["id"], []).append((crs_code, pre_code))
                except (ValueError, KeyError):
                    errors.append({"line": index, "code": "INVALID_ROW"})

            # DAG cycle validation per curriculum
            for cur_id, new_edges in curriculum_edges.items():
                existing = rows(db, """SELECT c.code AS course, p.code AS prereq FROM app.prerequisites pr
                  JOIN app.courses c ON c.id=pr.course_id JOIN app.courses p ON p.id=pr.prerequisite_course_id
                  WHERE pr.curriculum_id=:cid""", cid=cur_id)
                all_edges = [(r["course"], r["prereq"]) for r in existing] + new_edges
                try:
                    ac.detect_prerequisite_cycles(all_edges)
                except ValueError as exc:
                    errors.append({"line": 0, "code": "PREREQUISITE_CYCLE_DETECTED", "message": str(exc)})

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for cur_id, crs_id, pre_id, min_gp in validated:
                run(db, """INSERT INTO app.prerequisites(curriculum_id,course_id,prerequisite_course_id,min_grade_point)
                  VALUES(:cid,:crs_id,:pre_id,:gp)
                  ON CONFLICT(curriculum_id,course_id,prerequisite_course_id) DO UPDATE SET min_grade_point=excluded.min_grade_point""",
                    cid=cur_id, crs_id=crs_id, pre_id=pre_id, gp=min_gp)
                writes_count += 1

        # -------------------------------------------------------------
        # 7. GRADE_COMPONENTS
        # -------------------------------------------------------------
        elif normalized_type == "grade_components":
            fields = {"course_code", "semester_code", "component_code", "weight", "minimum_required"}
            records = _read_csv(content, fields)
            validated, seen = [], set()
            offering_weights = {}

            for index, row in enumerate(records, start=2):
                try:
                    crs_code = (row["course_code"] or "").strip()
                    sem_code = (row["semester_code"] or "").strip()
                    comp_code = (row["component_code"] or "").strip()
                    weight = ac.decimal(row["weight"], 0.01, 1.0)
                    min_req = ac.decimal(row["minimum_required"], 0, 10)
                    offering = one(db, """SELECT o.id FROM app.course_offerings o JOIN app.courses c ON c.id=o.course_id
                      JOIN app.semesters s ON s.id=o.semester_id WHERE c.code=:course AND s.code=:semester""", course=crs_code, semester=sem_code)
                    if not offering or not comp_code:
                        raise ValueError()
                    key = (str(offering["id"]), comp_code)
                    if key in seen:
                        raise ValueError()
                    seen.add(key)
                    validated.append((offering["id"], comp_code, weight, min_req))
                    offering_weights.setdefault(offering["id"], {})[comp_code] = weight
                except (ValueError, KeyError):
                    errors.append({"line": index, "code": "INVALID_ROW"})

            # Publish/update is only valid if the complete post-import component
            # set has the DEMO-1 exact total.  Existing rows not in this file remain.
            for off_id, replacements in offering_weights.items():
                current = {r["code"]: r["weight"] for r in rows(db,
                    "SELECT code,weight FROM app.assessment_components WHERE offering_id=:id", id=off_id)}
                current.update(replacements)
                if sum(current.values()) != 1:
                    errors.append(_error(0, "ASSESSMENT_WEIGHTS_NOT_ONE"))

            if errors or dry_run:
                return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))

            for off_id, comp_code, weight, min_req in validated:
                run(db, """INSERT INTO app.assessment_components(offering_id,code,weight,max_score,minimum_required)
                  VALUES(:oid,:code,:weight,10,:min_req)
                  ON CONFLICT(offering_id,code) DO UPDATE SET weight=excluded.weight,minimum_required=excluded.minimum_required""",
                    oid=off_id, code=comp_code, weight=weight, min_req=min_req)
                writes_count += 1

        elif normalized_type == "grade_component_scores":
            records = _read_csv(content, {"student_code", "course_code", "semester_code", "component_code", "score"})
            validated, seen = [], set()
            for line, row in enumerate(records, 2):
                try:
                    score = ac.decimal(row["score"], 0, 10)
                    student = one(db, "SELECT id FROM app.students WHERE student_code=:code AND domain_id='demo_academic' FOR UPDATE", code=(row["student_code"] or "").strip())
                    enrollment = one(db, """SELECT e.* FROM app.enrollments e JOIN app.course_offerings o ON o.id=e.offering_id
                      JOIN app.courses c ON c.id=o.course_id JOIN app.semesters s ON s.id=o.semester_id
                      WHERE e.student_id=:student AND c.code=:course AND s.code=:semester""",
                      student=student["id"] if student else None, course=(row["course_code"] or "").strip(), semester=(row["semester_code"] or "").strip())
                    component = one(db, """SELECT ac.id,ac.offering_id FROM app.assessment_components ac JOIN app.course_offerings o ON o.id=ac.offering_id
                      JOIN app.courses c ON c.id=o.course_id JOIN app.semesters s ON s.id=o.semester_id
                      WHERE c.code=:course AND s.code=:semester AND ac.code=:component""",
                      course=(row["course_code"] or "").strip(), semester=(row["semester_code"] or "").strip(), component=(row["component_code"] or "").strip())
                    if not student: raise LookupError("UNRESOLVED_STUDENT")
                    if not enrollment: raise LookupError("UNRESOLVED_ENROLLMENT")
                    if not component or component["offering_id"] != enrollment["offering_id"]: raise LookupError("COMPONENT_OFFERING_MISMATCH")
                    key = (str(enrollment["id"]), str(component["id"]))
                    if key in seen: raise ValueError("DUPLICATE_BUSINESS_KEY")
                    existing = one(db, "SELECT score FROM app.grade_components WHERE enrollment_id=:enrollment AND component_id=:component", enrollment=enrollment["id"], component=component["id"])
                    if enrollment["finalized_at"] and (not existing or existing["score"] != score): raise RuntimeError("FINALIZED_RECORD_CONFLICT")
                    seen.add(key); validated.append((student["id"], enrollment["id"], component["id"], score, existing))
                except LookupError as exc: errors.append(_error(line, str(exc)))
                except RuntimeError as exc: errors.append(_error(line, str(exc)))
                except Exception: errors.append(_error(line, "INVALID_GRADE_COMPONENT_SCORE"))
            if errors or dry_run: return _outcome(db, user["id"], normalized_type, digest, dry_run, errors, len(records))
            changed = set()
            for student_id, enrollment_id, component_id, score, existing in validated:
                if existing and existing["score"] == score: continue
                run(db, """INSERT INTO app.grade_components(enrollment_id,component_id,score) VALUES(:enrollment,:component,:score)
                    ON CONFLICT(enrollment_id,component_id) DO UPDATE SET score=excluded.score,observed_at=now(),available_at=now()""",
                    enrollment=enrollment_id, component=component_id, score=score)
                changed.add(student_id); writes_count += 1
            for student_id in changed:
                run(db, "UPDATE app.students SET academic_revision=academic_revision+1,updated_at=now() WHERE id=:id", id=student_id)

        return _outcome(db, user["id"], normalized_type, digest, False, [], len(records), writes_count)


@router.get("/admin/imports/{job_id}")
def import_status(job_id: UUID, user: Actor):
    require_role(user, "admin")
    with transaction() as db:
        job = one(db, "SELECT * FROM app.import_jobs WHERE id=:id", id=job_id)
        if not job:
            raise APIError("RESOURCE_NOT_FOUND", 404)
        return envelope(job)
