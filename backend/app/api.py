from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4
import csv
import hashlib
import io
import json
import os
import re
import secrets
import threading
import time
from fastapi import APIRouter, Depends, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field
from app import academic as ac
from app import ai_runtime
from app import responses as out
from app.security import access_token, decode_token, token_hash, verify_password
from app.store import transaction, one, rows, run

router = APIRouter(prefix="/api/v1")


class APIError(Exception):
    def __init__(self, code, status=422, message=None):
        self.code, self.status, self.message = code, status, message or code


def clean(value):
    if isinstance(value, Decimal):
        return ac.wire(value)
    if isinstance(value, (UUID, date, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def envelope(data):
    return {"data": clean(data), "meta": {"request_id": str(uuid4()), "contract_version": "1.0.0", "warnings": []}}


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


Score = Annotated[Decimal, Field(ge=0, le=10, decimal_places=6, allow_inf_nan=False)]
GPA = Annotated[Decimal, Field(ge=0, le=4, decimal_places=6, allow_inf_nan=False)]
Credits = Annotated[Decimal, Field(ge=0, le=126, decimal_places=6, allow_inf_nan=False)]


class Login(DTO):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Goal(DTO):
    target_gpa: GPA
    target_graduation_semester_id: UUID | None = None


class Required(DTO):
    target_gpa: GPA
    future_gpa_credits: Credits


class SelfReportedCourse(DTO):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    credits: Annotated[Decimal, Field(gt=0, le=30, decimal_places=6, allow_inf_nan=False)]
    score: Score
    attempt: int = Field(ge=1, le=20)


class SelfReportedPreview(DTO):
    courses: list[SelfReportedCourse] = Field(min_length=1, max_length=200)
    target_gpa: GPA = Decimal('3.2')
    future_gpa_credits: Credits = Decimal('0')
    policy: Literal['DEMO-1', 'POL-01-demo', 'ACADEMIC-DEMO-2.0.0'] = 'DEMO-1'


class Target(DTO):
    enrollment_id: UUID
    target_total_score: Score
    unknown_component_code: str = Field(max_length=40)


class Average(DTO):
    mode: Literal["semester_average"]
    assumed_gpa: GPA
    gpa_credits: Annotated[Decimal, Field(gt=0, le=126, decimal_places=6)]


class CourseScore(DTO):
    offering_id: UUID
    assumed_final_score: Score


class CourseSimulation(DTO):
    mode: Literal["course_scores"]
    items: list[CourseScore] = Field(min_length=1, max_length=42)


class Search(DTO):
    query: str = Field(min_length=1, max_length=2000)
    document_types: list[str] | None = None
    as_of: datetime | None = None
    corpus_scope: Literal['demo_academic', 'utt_test', 'utt_corpus'] = 'demo_academic'


class Message(DTO):
    message: str = Field(min_length=1, max_length=2000)
    client_turn_id: UUID


class ChatSessionCreate(DTO):
    corpus_scope: Literal['demo_academic', 'utt_test', 'utt_corpus'] = 'demo_academic'


class Assignment(DTO):
    advisor_user_id: UUID
    student_id: UUID


class Prediction(DTO):
    enrollment_id: UUID
    prediction_as_of: datetime


class ResearchFeatures(DTO):
    case_id: str = Field(min_length=1, max_length=200)
    # Research-only domains are explicitly enumerated here.  This does not
    # permit a student profile to become a research case; ownership and the
    # domain-specific schema are still checked below.
    domain_id: Literal["oulad", "academic_demo_v2"]
    data_origin: Literal["public_dataset", "synthetic"]
    feature_schema_id: str = Field(min_length=1, max_length=80)
    feature_schema_version: Literal["1.0.0"]
    cutoff_day: Literal[28]
    source_completeness: dict[str, bool]
    features: dict[str, int | float | None]


def actor(request: Request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise APIError("UNAUTHENTICATED", 401)
    try:
        claims = decode_token(header[7:])
        uid = UUID(claims["sub"])
    except RuntimeError:
        raise APIError("AUTH_NOT_CONFIGURED", 503)
    except Exception:
        raise APIError("UNAUTHENTICATED", 401)
    with transaction() as db:
        user = one(db, "SELECT id,email,role,auth_version FROM app.users WHERE id=:id AND is_active", id=uid)
    if not user or claims.get("ver", 0) != user["auth_version"]:
        raise APIError("UNAUTHENTICATED", 401)
    return user


Actor = Annotated[dict, Depends(actor)]


def require_role(user, *roles):
    if user["role"] not in roles:
        raise APIError("FORBIDDEN", 403)


def own_student(db, user):
    require_role(user, "student")
    student = one(db, "SELECT * FROM app.students WHERE user_id=:uid", uid=user["id"])
    if not student:
        raise APIError("STUDENT_PROFILE_NOT_LINKED", 409, "Tài khoản sinh viên chưa được liên kết với hồ sơ học vụ. Liên hệ quản trị viên để chọn đúng mapping users → students.")
    return student


def authorized_student(db, user, sid):
    student = one(db, "SELECT * FROM app.students WHERE id=:id", id=sid)
    if not student:
        raise APIError("RESOURCE_NOT_FOUND", 404)
    if user["role"] == "admin" or student["user_id"] == user["id"]:
        return student
    if user["role"] == "advisor" and one(db, "SELECT id FROM app.advisor_assignments WHERE advisor_user_id=:uid AND student_id=:sid", uid=user["id"], sid=sid):
        return student
    raise APIError("RESOURCE_NOT_FOUND", 404)


def transcript(db, student):
    return rows(db, """SELECT e.*,o.credits,o.semester_id,s.code AS semester_code,s.end_date,
      c.code,c.title,cc.counts_for_gpa FROM app.enrollments e
      JOIN app.course_offerings o ON o.id=e.offering_id
      JOIN app.semesters s ON s.id=o.semester_id JOIN app.courses c ON c.id=e.course_id
      JOIN app.curriculum_courses cc ON cc.course_id=c.id AND cc.curriculum_id=:curriculum
      WHERE e.student_id=:id ORDER BY s.end_date,c.code,e.attempt_no""",
      id=student["id"], curriculum=student["curriculum_id"])


def policy_code(db, student):
    policy = one(db, '''SELECT p.code FROM app.curricula c JOIN app.grading_policies p ON p.id=c.policy_id
      WHERE c.id=:id''', id=student['curriculum_id'])
    return policy['code'] if policy else None


def is_v2_policy(db, student):
    return policy_code(db, student) == 'ACADEMIC-DEMO-2'


def summary_service(db, student):
    data = transcript(db, student)
    is_v2 = is_v2_policy(db, student)
    if is_v2:
        from advisor_core.academic_policy_v2 import semester_history, transcript_summary
        result, history = transcript_summary(data), semester_history(data)
    else:
        result, history = ac.summary(data), ac.semester_history(data)
    passed = {r['course_id'] for r in data if r['status'] == 'P' or
              r['status'] == 'exempt' and r.get('recognized') or
              r['status'] == 'graded' and r['final_score'] >= 4 and r.get('minimums_met', True)}
    failed = [r for r in data if r['course_id'] not in passed and (r['status'] == 'F' or
              r['status'] == 'graded' and (r['final_score'] < 4 or not r.get('minimums_met', True)))]
    failed_codes = result.pop('failed_course_codes', ()) if is_v2 else ()
    curriculum = one(db, "SELECT code,total_required_credits FROM app.curricula WHERE id=:id",
                     id=student['curriculum_id'])
    if is_v2 and curriculum and curriculum['code'] == 'HTTT-UTT':
        latest = {}
        for row in data:
            if row['code'] not in latest or row['attempt_no'] > latest[row['code']]['attempt_no']:
                latest[row['code']] = row
        degree_earned = sum((Decimal(row['credits']) for row in latest.values()
            if row.get('counts_for_gpa') and (row['status'] == 'P'
                or row['status'] == 'exempt' and row.get('recognized')
                or row['status'] == 'graded' and row['final_score'] >= 4 and row.get('minimums_met', True))), Decimal(0))
        required_credits = Decimal(curriculum['total_required_credits'])
        result['earned_credits'] = ac.wire(degree_earned)
        result['required_credits'] = ac.wire(required_credits)
        result['remaining_required_credits'] = ac.wire(max(Decimal(0), required_credits-degree_earned))
    result['failed_courses'] = (sorted({str(r['course_id']) for r in failed}) if not is_v2 else
                                sorted({str(r['course_id']) for r in data if r['code'] in failed_codes}))
    result.update({"student_id": student["id"], "curriculum_id": student["curriculum_id"],
                   "academic_revision": student["academic_revision"], "transcript": data,
                   "semester_history": history, "trend": ac.academic_trend(history),
                   "failed_course_details": [{"course_id": r["course_id"], "code": r["code"], "attempt_no": r["attempt_no"], "status": r["status"]} for r in failed],
                   "domain_id": student["domain_id"], "progress_status": "demo_progress_not_official_graduation",
                   "assumptions": result.get('assumptions') if is_v2 else ["Semester GPA uses attempts in that semester", "Historical cumulative GPA excludes later retakes"]})
    result["goal"] = one(db, "SELECT target_gpa,target_graduation_semester_id FROM app.goals WHERE student_id=:id", id=student["id"])
    return result


_attempts = {}
_lock = threading.Lock()


def rate_limit(request, scope, maximum=20):
    # Single-process development limit, never trusts spoofed X-Forwarded-For.
    key = (request.client.host, scope)
    now = time.monotonic()
    with _lock:
        for old in [k for k, (_, until) in _attempts.items() if until < now]:
            del _attempts[old]
        count, until = _attempts.get(key, (0, now + 60))
        if count >= maximum:
            raise APIError("RATE_LIMITED", 429)
        _attempts[key] = (count + 1, until)


def refresh_cookie(response, token, request):
    response.set_cookie("advisor_refresh", token, httponly=True, samesite="strict",
                        secure=(request.url.scheme == "https" or
                                os.environ.get('APP_ENV') == 'production'),
                        path="/api/v1/auth", max_age=86400)


def issue(db, uid, response, request):
    # Generate access token first so missing key cannot leave a persisted session.
    account = one(db, "SELECT auth_version FROM app.users WHERE id=:id AND is_active FOR UPDATE", id=uid)
    if not account:
        raise APIError("UNAUTHENTICATED", 401)
    access = access_token(uid, account["auth_version"])
    raw = secrets.token_urlsafe(48)
    session = one(db, """INSERT INTO app.refresh_sessions(user_id,token_hash,expires_at)
      VALUES(:uid,:hash,:expiry) RETURNING id""", uid=uid, hash=token_hash(raw), expiry=datetime.now(timezone.utc)+timedelta(days=1))
    refresh_cookie(response, raw, request)
    return {"access_token": access, "token_type": "bearer", "expires_in": 900}, session["id"]


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    rate_limit(request, "login", 10)
    with transaction() as db:
        user = one(db, "SELECT * FROM app.users WHERE (lower(email)=:email OR lower(username)=:email) AND is_active FOR UPDATE", email=body.email.strip().lower())
        if not user or not verify_password(body.password, user["password_hash"]):
            raise APIError("UNAUTHENTICATED", 401, "Tên đăng nhập hoặc mật khẩu không đúng")
        tokens, _ = issue(db, user["id"], response, request)
        tokens["user"] = {k: user[k] for k in ("id", "email", "role")}
        return envelope(tokens)


def same_origin(request):
    from urllib.parse import urlsplit
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise APIError("FORBIDDEN", 403)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response):
    same_origin(request)
    rate_limit(request, "refresh", 30)
    with transaction() as db:
        current = one(db, """SELECT s.* FROM app.refresh_sessions s JOIN app.users u ON u.id=s.user_id
          WHERE s.token_hash=:hash AND u.is_active AND s.revoked_at IS NULL AND s.expires_at>now() FOR UPDATE OF s""",
                      hash=token_hash(request.cookies.get("advisor_refresh", "")))
        if not current:
            raise APIError("UNAUTHENTICATED", 401)
        tokens, replacement = issue(db, current["user_id"], response, request)
        run(db, "UPDATE app.refresh_sessions SET revoked_at=now(),replaced_by=:replacement WHERE id=:id", replacement=replacement, id=current["id"])
        tokens["user"] = one(db, "SELECT id,email,role FROM app.users WHERE id=:id", id=current["user_id"])
        return envelope(tokens)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    same_origin(request)
    with transaction() as db:
        run(db, "UPDATE app.refresh_sessions SET revoked_at=now() WHERE token_hash=:hash", hash=token_hash(request.cookies.get("advisor_refresh", "")))
    response.delete_cookie("advisor_refresh", path="/api/v1/auth")
    return envelope({"logged_out": True})


@router.get("/students/me")
def profile(user: Actor):
    with transaction() as db:
        return envelope(own_student(db, user))


@router.get("/students/{student_id}/academic-summary", response_model=out.Envelope[out.AcademicSummary])
def academic_summary(student_id: UUID, user: Actor):
    with transaction() as db:
        return envelope(summary_service(db, authorized_student(db, user, student_id)))


@router.patch("/students/me/goal")
def save_goal(body: Goal, user: Actor):
    with transaction() as db:
        student = own_student(db, user)
        if body.target_graduation_semester_id and not one(db, "SELECT id FROM app.semesters WHERE id=:id", id=body.target_graduation_semester_id):
            raise APIError("RESOURCE_NOT_FOUND", 404)
        run(db, """INSERT INTO app.goals(student_id,target_gpa,target_graduation_semester_id) VALUES(:id,:target,:semester)
          ON CONFLICT(student_id) DO UPDATE SET target_gpa=excluded.target_gpa,
          target_graduation_semester_id=excluded.target_graduation_semester_id,updated_at=now()""",
            id=student["id"], target=body.target_gpa, semester=body.target_graduation_semester_id)
        return envelope(body.model_dump())


@router.post("/academic/required-gpa", response_model=out.Envelope[out.RequiredGPA])
def required(body: Required, user: Actor):
    with transaction() as db:
        student = own_student(db, user)
        data = transcript(db, student)
        if is_v2_policy(db, student):
            from advisor_core.academic_policy_v2 import required_gpa, transcript_summary
            result = required_gpa(transcript_summary(data), body.target_gpa, body.future_gpa_credits)
        else:
            current = ac.summary(data, raw=True)
            result = ac.required_gpa(current["quality_points"], current["gpa_credits"], body.target_gpa, body.future_gpa_credits)
        result["academic_revision"] = student["academic_revision"]
        return envelope(result)


@router.post('/academic/self-reported/preview')
def self_reported_preview(body: SelfReportedPreview, user: Actor):
    # Explicit self-report boundary: never merge with or write official records.
    if user['role'] != 'student':
        raise APIError('FORBIDDEN', 403)
    attempts, credits, entries = set(), {}, []
    for item in body.courses:
        code = item.code.upper()
        if (code, item.attempt) in attempts:
            raise APIError('DUPLICATE_ATTEMPT', 422, 'Trùng mã môn và lần học.')
        if code in credits and credits[code] != item.credits:
            raise APIError('INCONSISTENT_CREDITS', 422, 'Các lần học cùng môn phải có cùng số tín chỉ.')
        attempts.add((code, item.attempt))
        credits[code] = item.credits
        entries.append(dict(course_id=code, credits=item.credits, final_score=item.score,
                            attempt_no=item.attempt, status='graded'))
    result = ac.summary(entries)
    raw = ac.summary(entries, raw=True)
    result['gpa_10'] = ac.wire(raw['quality_points'] / raw['gpa_credits'] / Decimal('.4')) if raw['gpa_credits'] else None
    result['gpa_4'] = result['cumulative_gpa']
    if body.policy == 'ACADEMIC-DEMO-2.0.0':
        from advisor_core.academic_policy_v2 import NON_GPA_COURSES, preview_attempts, required_gpa
        v2_rows = [dict(course=item.code.upper(), attempt=item.attempt, credits=item.credits, score=item.score,
                        gpa_bearing=item.code.upper() not in NON_GPA_COURSES, status='graded') for item in body.courses]
        result = preview_attempts(v2_rows)
        result.update(cumulative_gpa=result['gpa_4'], quality_points=result['quality_points_4'],
                      required_credits='130.000000',
                      remaining_required_credits=ac.wire(max(Decimal(0), Decimal(130) - Decimal(result['earned_credits']))))
        raw = None
    elif body.policy == 'POL-01-demo':
        from advisor_core.academic_demo_policy import dual_gpa
        dual = dual_gpa([item.model_dump() for item in body.courses])
        result.update(dual, cumulative_gpa=dual['gpa_4'], quality_points=dual['quality_points_4'], required_credits='130.000000',
                      remaining_required_credits=ac.wire(max(Decimal(0), Decimal(130) - Decimal(dual['earned_credits']))))
        # Credit count alone does not establish programme completion.
        raw = dict(quality_points=Decimal(dual['quality_points_4']), gpa_credits=Decimal(dual['gpa_credits']))
    result['data_origin'] = 'self_reported'
    goal = (required_gpa(result, body.target_gpa, body.future_gpa_credits)
            if body.policy == 'ACADEMIC-DEMO-2.0.0' else
            ac.required_gpa(raw['quality_points'], raw['gpa_credits'], body.target_gpa, body.future_gpa_credits))
    goal['data_origin'] = 'self_reported'
    goal['policy_version'] = body.policy
    return envelope({'summary': result, 'goal': goal, 'persisted': False,
                     'warnings': [f'Dữ liệu tự khai; tính thử theo {body.policy}.',
                                  ('Học lại lấy lần mới nhất; PE và quốc phòng-an ninh không tính GPA.'
                                   if body.policy == 'ACADEMIC-DEMO-2.0.0' else
                                   'Mọi môn nhập đều tính GPA; học lại lấy điểm cao nhất. GPA mục tiêu sử dụng thang 4.'),
                                  'Chỉ hỗ trợ môn có điểm thang 10; chưa xác minh điều kiện điểm thành phần.']})


@router.post("/academic/target-score", response_model=out.Envelope[out.TargetScore])
def target(body: Target, user: Actor):
    with transaction() as db:
        student = own_student(db, user)
        enrollment = one(db, "SELECT * FROM app.enrollments WHERE id=:id AND student_id=:sid", id=body.enrollment_id, sid=student["id"])
        if not enrollment:
            raise APIError("RESOURCE_NOT_FOUND", 404)
        components = rows(db, """SELECT c.code,c.weight,c.minimum_required,g.score FROM app.assessment_components c
          LEFT JOIN app.grade_components g ON g.component_id=c.id AND g.enrollment_id=:id WHERE c.offering_id=:offering""",
                          id=enrollment["id"], offering=enrollment["offering_id"])
        result = ac.target_score(components, body.target_total_score, body.unknown_component_code)
        if is_v2_policy(db, student):
            result.update(policy_version='ACADEMIC-DEMO-2.0.0', data_origin='synthetic',
                          assumptions=['Assessment-component arithmetic; this response does not itself calculate GPA.'])
        return envelope(result)


@router.post("/academic/simulations", response_model=out.Envelope[out.Simulation])
def simulate(body: Annotated[Average | CourseSimulation, Field(discriminator="mode")], user: Actor):
    with transaction() as db:
        student = own_student(db, user)
        original = transcript(db, student)
        v2 = is_v2_policy(db, student)
        if v2:
            from advisor_core.academic_policy_v2 import transcript_summary
            before = transcript_summary(original)
        else:
            before = ac.summary(original)
        if body.mode == "semester_average":
            if v2:
                # A planned term average is a 4-point planning value.  It cannot
                # be converted to a truthful 10-point GPA without course scores.
                from advisor_core.academic_policy_v2 import project_gpa_4
                projection = project_gpa_4(before, body.assumed_gpa, body.gpa_credits)
                after = {**before, "cumulative_gpa": projection['projected_gpa'],
                         "gpa_4": projection['projected_gpa'], "gpa_10": None,
                         "quality_points": projection['projected_quality_points_4'],
                         "quality_points_4": projection['projected_quality_points_4'],
                         "gpa_credits": projection['projected_gpa_credits'],
                         "projection_scale": projection['projection_scale']}
            else:
                precise = ac.summary(original, raw=True)
                after_credits = precise["gpa_credits"] + body.gpa_credits
                qp = precise["quality_points"] + body.gpa_credits * body.assumed_gpa
                after = {"cumulative_gpa": ac.wire(qp / after_credits), "quality_points": ac.wire(qp), "gpa_credits": ac.wire(after_credits)}
        else:
            if len({i.offering_id for i in body.items}) != len(body.items):
                raise APIError("DUPLICATE_OFFERING")
            hypothetical = [dict(r) for r in original]
            seen_courses = set()
            for item in body.items:
                offering = one(db, """SELECT o.*,c.code FROM app.course_offerings o JOIN app.courses c ON c.id=o.course_id
                  JOIN app.curriculum_courses cc ON cc.course_id=o.course_id AND cc.curriculum_id=:curriculum WHERE o.id=:id""", id=item.offering_id, curriculum=student["curriculum_id"])
                if not offering or offering["course_id"] in seen_courses:
                    raise APIError("INVALID_OFFERING")
                seen_courses.add(offering["course_id"])
                existing = [r for r in hypothetical if r["offering_id"] == item.offering_id]
                if existing:
                    existing[0].update(status="graded", final_score=item.assumed_final_score, minimums_met=True)
                else:
                    attempt = max([r["attempt_no"] for r in original if r["course_id"] == offering["course_id"]] or [0]) + 1
                    hypothetical.append({"offering_id": item.offering_id, "course_id": offering["course_id"], "code": offering["code"], "credits": offering["credits"], "attempt_no": attempt,
                                         "status": "graded", "final_score": item.assumed_final_score})
            after = transcript_summary(hypothetical) if v2 else ac.summary(hypothetical)
        return envelope({"before": before, "after": after, "academic_revision": student["academic_revision"],
                         "policy_version": "ACADEMIC-DEMO-2.0.0" if v2 else "DEMO-1", "data_origin": "synthetic", "persisted": False,
                         "assumptions": ["Mô phỏng; không thay bảng điểm", "Điểm giả định đáp ứng minimum thành phần"] +
                         (["Mô phỏng trung bình học kỳ chỉ có ý nghĩa thang 4; không suy diễn GPA thang 10."] if v2 and body.mode == 'semester_average' else [])})


def page(items, limit, cursor):
    import base64
    if not 1 <= limit <= 100:
        raise APIError("INVALID_PAGE")
    try:
        offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        if offset < 0:
            raise ValueError()
    except Exception:
        raise APIError("INVALID_CURSOR")
    return {"items": items[offset:offset+limit], "next_cursor": base64.urlsafe_b64encode(str(offset+limit).encode()).decode() if offset+limit < len(items) else None}


@router.get("/catalog/semesters")
def semesters(user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        return envelope(page(rows(db, "SELECT * FROM app.semesters ORDER BY code"), limit, cursor))


def _curriculum_options(db):
    return rows(db, """SELECT id,code,version,major,faculty,total_required_credits,
                      status,source_name,source_sha256
               FROM app.curricula
               WHERE status='demo'
               ORDER BY major,version,code""")


@router.get("/catalog/curricula", response_model=out.Envelope[out.CurriculumCatalog])
def curricula_catalog(user: Actor):
    """Authenticated pilot catalog used by profile selection and admin imports."""
    with transaction() as db:
        return envelope({"items": _curriculum_options(db)})


@router.get("/catalog/curricula/{curriculum_id}/courses")
def courses(curriculum_id: UUID, user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        if user["role"] == "student" and own_student(db, user)["curriculum_id"] != curriculum_id:
            raise APIError("RESOURCE_NOT_FOUND", 404)
        data = rows(db, """SELECT c.*,cc.credits,cc.required,cc.recommended_term_no FROM app.curriculum_courses cc
          JOIN app.courses c ON c.id=cc.course_id WHERE cc.curriculum_id=:id ORDER BY c.code""", id=curriculum_id)
        return envelope(page(data, limit, cursor))


@router.get("/catalog/offerings")
def offerings(semester_id: UUID, user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        return envelope(page(rows(db, """SELECT o.*,c.code,c.title FROM app.course_offerings o JOIN app.courses c ON c.id=o.course_id
          WHERE o.semester_id=:id ORDER BY c.code""", id=semester_id), limit, cursor))


@router.get("/advisor/students")
def assigned_students(user: Actor, limit: int = 20, cursor: str | None = None):
    require_role(user, "advisor", "admin")
    with transaction() as db:
        data = rows(db, """SELECT s.* FROM app.students s WHERE :admin OR EXISTS
          (SELECT 1 FROM app.advisor_assignments a WHERE a.student_id=s.id AND a.advisor_user_id=:uid)
          ORDER BY s.student_code""", admin=user["role"] == "admin", uid=user["id"])
        return envelope(page(data, limit, cursor))


@router.post("/admin/advisor-assignments")
def assign(body: Assignment, user: Actor):
    require_role(user, "admin")
    with transaction() as db:
        if not one(db, "SELECT id FROM app.users WHERE id=:id AND role='advisor' AND is_active", id=body.advisor_user_id):
            raise APIError("INVALID_ADVISOR")
        authorized_student(db, user, body.student_id)
        run(db, "INSERT INTO app.advisor_assignments(advisor_user_id,student_id) VALUES(:uid,:sid) ON CONFLICT DO NOTHING", uid=body.advisor_user_id, sid=body.student_id)
        return envelope({"assigned": True})


def recommend_service(db, student, semester_id, target_course_ids=()):
    if not one(db, 'SELECT id FROM app.semesters WHERE id=:id', id=semester_id):
        raise APIError('RESOURCE_NOT_FOUND', 404)
    history = transcript(db, student)
    v2 = is_v2_policy(db, student)
    if v2:
        from advisor_core.academic_policy_v2 import NON_GPA_COURSES, normalize_attempt
        latest = {}
        for r in history:
            normalized = normalize_attempt(course=r['code'], attempt=int(r['attempt_no']), credits=r['credits'],
                score=r['final_score'] if r['status'] == 'graded' else None,
                gpa_bearing=r.get('counts_for_gpa', r['code'] not in NON_GPA_COURSES),
                status='graded' if r['status'] == 'graded' else 'absent_or_barred')
            if r['course_id'] not in latest or normalized['attempt'] > latest[r['course_id']]['attempt']['attempt']:
                latest[r['course_id']] = {'attempt': normalized, 'row': r}
        passed = {course_id for course_id, item in latest.items() if item['attempt']['completed']}
        points = {course_id: item['attempt']['effective_score_4'] for course_id, item in latest.items()}
    else:
        passed = {r['course_id'] for r in history if r['status'] == 'P' or
                  r['status'] == 'exempt' and r.get('recognized') or
                  r['status'] == 'graded' and r['final_score'] >= 4 and r.get('minimums_met', True)}
        points = {}
        for r in history:
            if r['status'] == 'graded' and r.get('minimums_met', True):
                points[r['course_id']] = max(points.get(r['course_id'], Decimal(0)), r['final_score'] * Decimal('.4'))
    candidates = rows(db, """SELECT o.*,c.code,c.title,cc.recommended_term_no FROM app.course_offerings o
      JOIN app.courses c ON c.id=o.course_id JOIN app.curriculum_courses cc ON cc.course_id=c.id
      WHERE cc.curriculum_id=:cid AND o.semester_id=:sid ORDER BY cc.recommended_term_no,c.code""", cid=student["curriculum_id"], sid=semester_id)
    prerequisites = rows(db, "SELECT * FROM app.prerequisites WHERE curriculum_id=:id", id=student["curriculum_id"])
    ac.detect_prerequisite_cycles([(str(p['course_id']), str(p['prerequisite_course_id'])) for p in prerequisites])
    eligible, excluded = [], []
    target_course_ids = {str(value) for value in target_course_ids}
    path = ac.learning_paths([(p['course_id'], p['prerequisite_course_id']) for p in prerequisites], target_course_ids)
    for c in candidates:
        missing = [str(p['prerequisite_course_id']) for p in prerequisites if p['course_id'] == c['course_id'] and
                   (p['prerequisite_course_id'] not in passed or points.get(p['prerequisite_course_id'], Decimal(-1)) < p['min_grade_point'])]
        reason = "already_passed" if c["course_id"] in passed else "offering_closed" if not c["is_open"] else "prerequisite_missing" if missing else None
        if reason:
            excluded.append({"offering_id": c["id"], "code": c["code"], "reason": reason, "missing": missing})
        else:
            c["reason"] = "required_unpassed"
            c["retake"] = (c["course_id"] in latest if v2 else
                            any(r["course_id"] == c["course_id"] and r["status"] == "graded" for r in history))
            c["unlocks"] = sum(p["prerequisite_course_id"] == c["course_id"] for p in prerequisites)
            c["independent"] = c["unlocks"] == 0 and not any(p["course_id"] == c["course_id"] for p in prerequisites)
            c["target"] = str(c["course_id"]) in target_course_ids
            c['target_ancestor'] = str(c['course_id']) in path['union']
            eligible.append(c)
    eligible.sort(key=lambda c: (not c["target_ancestor"], not c["retake"],
                                 c["recommended_term_no"] or 999, -c["unlocks"], c["code"]))
    selected, credits = [], Decimal(0)
    for c in eligible:
        if credits+c["credits"] <= 18:
            selected.append(c)
            credits += c["credits"]
    excluded.extend({"offering_id": None, "code": str(target), "reason": "target_not_offered_or_not_in_curriculum", "missing": []}
                    for target in target_course_ids if target not in {str(c["course_id"]) for c in candidates})
    return {"selected": selected, "eligible": eligible, "excluded": excluded, "total_credits": credits,
            'learning_paths': path,
            "policy_version": "ACADEMIC-DEMO-2.0.0" if v2 else "DEMO-1", "data_origin": "synthetic", "algorithm": "deterministic_greedy",
            "assumptions": (["Prerequisites use the latest resolved v2 attempt; non-GPA PE/defence courses remain pass/fail."] if v2 else
                            ["AND-only prerequisites; numeric minimum required, P/exempt alone does not prove it"]) +
                           ["Multiple targets are prioritized but not guaranteed", "No timetable or capacity data"],
            "unsupported_rule_state": "needs_manual_review", "unchecked_constraints": ["Lịch học", "Sĩ số", "Quy chế chính thức"], "is_optimal": False}


@router.get("/recommendations/courses", response_model=out.Envelope[out.Recommendations])
def recommendations(semester_id: UUID, user: Actor, target_course_ids: Annotated[list[UUID] | None, Query()] = None):
    with transaction() as db:
        return envelope(recommend_service(db, own_student(db, user), semester_id, target_course_ids or ()))


def allow_corpus(user, corpus_scope):
    if corpus_scope == 'demo_academic':
        return
    if user['role'] == 'admin':
        return
    if user['role'] == 'student':
        with transaction() as db:
            demo = one(db, "SELECT id FROM app.students WHERE user_id=:uid", uid=user['id'])
        if demo:
            return
    if corpus_scope == 'utt_corpus':
        raise APIError('FORBIDDEN', 403, 'Kho UTT-Corpus chỉ dành cho admin và sinh viên đã liên kết hồ sơ.')
    raise APIError('FORBIDDEN', 403, 'Kho UTT-test chỉ dành cho admin và sinh viên demo đã liên kết hồ sơ.')


@router.post("/knowledge/search")
def search(body: Search, user: Actor):
    from app.knowledge import search as knowledge_search, resolve_actor_scope
    allow_corpus(user, body.corpus_scope)
    scope = resolve_actor_scope(user) if body.corpus_scope == 'utt_corpus' else {'major': None, 'cohort': None}
    return envelope(knowledge_search(body.query, body.as_of, body.document_types, body.corpus_scope,
                                    major=scope['major'], cohort=scope['cohort']))


@router.get("/knowledge/chunks/{chunk_id}")
def chunk(chunk_id: str, user: Actor, corpus_scope: Literal['demo_academic', 'utt_test', 'utt_corpus'] = 'demo_academic'):
    from app.knowledge import accessible_chunks, resolve_actor_scope
    allow_corpus(user, corpus_scope)
    scope = resolve_actor_scope(user) if corpus_scope == 'utt_corpus' else {'major': None, 'cohort': None}
    chunks = accessible_chunks(corpus_scope=corpus_scope, major=scope['major'], cohort=scope['cohort'])
    found = next((item for item in chunks if item["chunk_id"] == chunk_id), None)
    if not found:
        raise APIError("RESOURCE_NOT_FOUND", 404)
    return envelope({k: v for k, v in found.items() if k != "text"} | {"excerpt": found["text"]})


@router.post("/chat/sessions", response_model=out.Envelope[out.ChatSession])
def create_session(user: Actor, body: ChatSessionCreate = ChatSessionCreate()):
    allow_corpus(user, body.corpus_scope)
    with transaction() as db:
        return envelope(one(db, "INSERT INTO app.chat_sessions(user_id,corpus_scope) VALUES(:uid,:scope) RETURNING id,expires_at,corpus_scope", uid=user["id"], scope=body.corpus_scope))


@router.get('/chat/sessions')
def chat_sessions(user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        return envelope(page(rows(db, '''SELECT id,created_at,expires_at,corpus_scope FROM app.chat_sessions
            WHERE user_id=:uid AND expires_at>now() ORDER BY created_at DESC,id DESC''', uid=user['id']), limit, cursor))


def session_owner(db, user, sid):
    session = one(db, "SELECT id,corpus_scope FROM app.chat_sessions WHERE id=:id AND user_id=:uid AND expires_at>now() FOR UPDATE", id=sid, uid=user["id"])
    if not session:
        raise APIError("RESOURCE_NOT_FOUND", 404)
    allow_corpus(user, session['corpus_scope'])
    return session


@router.get("/chat/sessions/{session_id}/messages")
def messages(session_id: UUID, user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        session_owner(db, user, session_id)
        return envelope(page(rows(db, "SELECT client_turn_id,content,result,created_at FROM app.chat_messages WHERE session_id=:sid ORDER BY created_at,id", sid=session_id), limit, cursor))


@router.post("/chat/sessions/{session_id}/messages", response_model=out.Envelope[out.ChatTurn], response_model_exclude_unset=True)
def chat(session_id: UUID, body: Message, user: Actor, request: Request):
    rate_limit(request, "chat", 30)
    from app.chat_guard import session_guard
    from app.chat_service import dispatch
    # Check owner before taking a session lock; arbitrary IDs never grant access.
    with transaction() as db:
        session = session_owner(db, user, session_id)
    with session_guard(session_id):
        with transaction() as db:
            session = session_owner(db, user, session_id)
            previous = one(db, "SELECT content,result FROM app.chat_messages WHERE session_id=:sid AND client_turn_id=:tid", sid=session_id, tid=body.client_turn_id)
            if previous:
                if previous["content"] != body.message:
                    raise APIError("TURN_CONFLICT", 409)
                return envelope(previous["result"])
            latest = one(db, "SELECT result FROM app.chat_messages WHERE session_id=:sid ORDER BY created_at DESC,id DESC LIMIT 1", sid=session_id)
        result = dispatch(body.message, user, latest["result"] if latest else None, corpus_scope=session['corpus_scope'])
        with transaction() as db:
            session_owner(db, user, session_id)
            run(db, "INSERT INTO app.chat_messages(session_id,client_turn_id,content,result,created_at) VALUES(:sid,:tid,:content,CAST(:result AS jsonb),clock_timestamp())",
                sid=session_id, tid=body.client_turn_id, content=body.message, result=json.dumps(result, ensure_ascii=False))
        return envelope(result)


@router.get("/research-cases", response_model=out.Envelope[out.ResearchCasePage])
def research(user: Actor, limit: int = 20, cursor: str | None = None):
    with transaction() as db:
        return envelope(page(rows(db, """SELECT id,source_case_key,domain_id,data_origin
            FROM app.research_cases WHERE owner_user_id=:uid ORDER BY id""", uid=user["id"]), limit, cursor))


@router.get("/admin/research/dashboard", response_model=out.Envelope[out.ResearchDashboard])
def research_dashboard(user: Actor):
    """Aggregate synthetic research evidence; never infer or expose profiles."""
    require_role(user, "admin")
    with transaction() as db:
        counts = one(db, """WITH scoped_cases AS (
            SELECT id FROM app.research_cases
            WHERE domain_id='academic_demo_v2' AND data_origin='synthetic'
          ), snapshot_totals AS (
            SELECT count(*) AS snapshot_count FROM app.feature_snapshots s
            JOIN scoped_cases c ON c.id=s.research_case_id
          ), prediction_totals AS (
            SELECT count(*) AS prediction_count,
              count(*) FILTER (WHERE p.risk_label='at_risk') AS at_risk_count,
              count(*) FILTER (WHERE p.risk_label='not_at_risk') AS not_at_risk_count,
              avg(p.probability) AS average_probability
            FROM app.predictions p JOIN scoped_cases c ON c.id=p.research_case_id
          )
          SELECT (SELECT count(*) FROM scoped_cases) AS case_count,
            s.snapshot_count,p.prediction_count,p.at_risk_count,p.not_at_risk_count,p.average_probability
          FROM snapshot_totals s CROSS JOIN prediction_totals p""")
        versions = rows(db, """SELECT m.model_id,m.model_version,m.manifest_sha256,count(p.id) AS prediction_count
          FROM app.model_versions m LEFT JOIN app.predictions p ON p.model_version_id=m.id
          WHERE m.domain_id='academic_demo_v2'
          GROUP BY m.id,m.model_id,m.model_version,m.manifest_sha256
          ORDER BY m.model_version""")
    case_count = int(counts["case_count"] or 0)
    return envelope({
        "domain_id": "academic_demo_v2", "data_origin": "synthetic",
        "expected_case_count": 1000, "case_count": case_count,
        "snapshot_count": int(counts["snapshot_count"] or 0),
        "prediction_count": int(counts["prediction_count"] or 0),
        "at_risk_count": int(counts["at_risk_count"] or 0),
        "not_at_risk_count": int(counts["not_at_risk_count"] or 0),
        "average_probability": float(counts["average_probability"]) if counts["average_probability"] is not None else None,
        "coverage_status": "complete" if case_count == 1000 else ("partial" if case_count else "empty"),
        "model_versions": versions,
        "limitations": [
            "Dữ liệu nghiên cứu mô phỏng; không phải hồ sơ sinh viên thật.",
            "Dashboard chỉ tổng hợp prediction đã lưu; không tự động chạy inference.",
            "Xác suất phục vụ trình diễn và nghiên cứu, không dùng để ra quyết định học vụ.",
        ],
    })


@router.get("/admin/majors", response_model=out.Envelope[out.MajorOptions])
def list_majors(user: Actor):
    """Backward-compatible admin view of the authenticated curriculum catalog."""
    require_role(user, "admin")
    with transaction() as db:
        return envelope({"majors": _curriculum_options(db)})


@router.post("/research-cases/{case_id}/predictions", response_model=out.Envelope[out.ResearchPrediction])
def research_prediction(case_id: UUID, user: Actor):
    with transaction() as db:
        case = one(db, "SELECT id,domain_id,data_origin FROM app.research_cases WHERE id=:id AND (owner_user_id=:uid OR :admin)", id=case_id, uid=user["id"], admin=user["role"] == "admin")
        if not case:
            raise APIError("RESOURCE_NOT_FOUND", 404)
        snapshot = one(db, "SELECT * FROM app.feature_snapshots WHERE research_case_id=:id ORDER BY created_at DESC LIMIT 1", id=case_id)
        if not snapshot:
            raise APIError("INSUFFICIENT_FEATURES", 422, "Research case chưa có snapshot ML đã xác thực")
        if snapshot["domain_id"] != case["domain_id"] or snapshot["data_origin"] != case["data_origin"]:
            raise APIError("NOT_APPLICABLE", 422, "Snapshot không cùng miền dữ liệu với research case")
        approved=ai_runtime.approved_bundle(case["domain_id"])
        if not approved: raise APIError('MODEL_NOT_READY',503)
        sha=ai_runtime._sha(approved['bundle']/'manifest.json')
        active=one(db,'SELECT id FROM app.model_versions WHERE manifest_sha256=:sha AND is_active',sha=sha)
        if not active: raise APIError('MODEL_NOT_ACTIVATED',503)
        try:
            result = ai_runtime.predict({'case_id':str(case_id), 'domain_id':snapshot['domain_id'],'data_origin':snapshot['data_origin'],
                'features':snapshot['features_json'],'feature_schema_id':snapshot['feature_schema_id'],'feature_schema_version':snapshot['feature_schema_version'],
                'cutoff_day':snapshot['cutoff_day'],'source_completeness':snapshot['source_completeness']})
        except ai_runtime.AIRuntimeError as exc:
            code = str(exc)
            if code in {"MODEL_DOMAIN_MISMATCH", "INVALID_FEATURE_VECTOR"}:
                raise APIError("NOT_APPLICABLE", 422, "Research case không tương thích với model đang hoạt động") from exc
            raise APIError(code, 503 if code.startswith("MODEL_") else 422) from exc
        manifest = result["manifest"]
        manifest_sha = result['manifest_sha256']
        model = one(db, "SELECT id FROM app.model_versions WHERE bundle_name=:name AND manifest_sha256=:sha AND is_active", name=result["bundle_name"], sha=manifest_sha)
        if not model:
            raise APIError("MODEL_NOT_ACTIVATED", 503)
        created = one(db, """INSERT INTO app.predictions(research_case_id,feature_snapshot_id,model_version_id,probability,threshold,risk_label,explanation_json)
          VALUES(:case,:snapshot,:model,:probability,:threshold,:label,CAST(:explanation AS jsonb)) RETURNING id,created_at""", case=case_id, snapshot=snapshot["id"], model=model["id"], probability=result["probability"], threshold=result["threshold"], label=result["risk_label"],explanation=json.dumps(result['explanation']))
        if snapshot["domain_id"] == "academic_demo_v2":
            disclaimer = "Kết quả mô phỏng Academic Demo v2 từ tín hiệu sự kiện tổng hợp đến ngày 28; không phải dự báo cá nhân và không áp dụng cho hồ sơ sinh viên thật."
        else:
            disclaimer = ('Kết quả nghiên cứu mô phỏng OULAD-style, không áp dụng cho hồ sơ sinh viên.'
                          if snapshot['data_origin'] == 'synthetic' else 'Kết quả nghiên cứu OULAD, không áp dụng cho hồ sơ NTTU/DEMO.')
        return envelope({**created, "domain_id": snapshot["domain_id"], "data_origin": snapshot['data_origin'], "model_id": manifest["model_id"], "model_version": manifest["model_version"], "probability": result["probability"], "threshold": result["threshold"], "risk_label": result["risk_label"], "disclaimer": disclaimer})


@router.post("/research-cases/{case_id}/feature-snapshots")
def save_research_features(case_id: UUID, body: ResearchFeatures, user: Actor):
    if str(case_id) != body.case_id:
        raise APIError("CASE_ID_MISMATCH")
    from advisor_core.ml_boundary import validate_features
    record = body.model_dump()
    try:
        from advisor_core.ml_boundary import model_profile
        profile = model_profile(body.domain_id)
        if body.data_origin not in profile["data_origins"]:
            raise ValueError("MODEL_DOMAIN_MISMATCH")
        validate_features(record, f"/contracts/{profile['schema_file']}", allow_synthetic=body.domain_id == 'oulad' and body.data_origin == 'synthetic')
    except Exception as exc:
        from jsonschema import ValidationError
        if isinstance(exc,(ValueError,ValidationError)):
            raise APIError('INVALID_FEATURE_RECORD',422) from exc
        raise
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with transaction() as db:
        if not one(db, "SELECT id FROM app.research_cases WHERE id=:id AND (owner_user_id=:uid OR :admin)", id=case_id, uid=user["id"], admin=user["role"] == "admin"):
            raise APIError("RESOURCE_NOT_FOUND", 404)
        created = one(db, """INSERT INTO app.feature_snapshots(research_case_id,domain_id,data_origin,feature_schema_id,feature_schema_version,cutoff_day,features_json,source_completeness,snapshot_sha256,created_by)
          VALUES(:case,:domain,:origin,:schema_id,:schema_version,:cutoff,CAST(:features AS jsonb),CAST(:source AS jsonb),:sha,:user)
          ON CONFLICT(snapshot_sha256) DO NOTHING RETURNING id,created_at""", case=case_id, domain=body.domain_id, origin=body.data_origin, schema_id=body.feature_schema_id, schema_version=body.feature_schema_version, cutoff=body.cutoff_day, features=json.dumps(body.features), source=json.dumps(body.source_completeness), sha=digest, user=user["id"])
        if not created:
            created = one(db, "SELECT id,created_at FROM app.feature_snapshots WHERE snapshot_sha256=:sha", sha=digest)
        return envelope({**created, "snapshot_sha256": digest, "domain_id": body.domain_id, "data_origin": body.data_origin})


@router.post("/predictions")
def predict(body: Prediction, user: Actor):
    with transaction() as db:
        student = own_student(db, user)
        if not one(db, "SELECT id FROM app.enrollments WHERE id=:id AND student_id=:sid", id=body.enrollment_id, sid=student["id"]):
            raise APIError("RESOURCE_NOT_FOUND", 404)
    raise APIError("NOT_APPLICABLE", 422, "Không tự động áp model nghiên cứu lên hồ sơ sinh viên")


@router.get("/predictions/{prediction_id}")
def prediction_history(prediction_id: UUID, user: Actor):
    with transaction() as db:
        result=one(db,'''SELECT p.*,m.model_id,m.model_version,m.domain_id FROM app.predictions p
          JOIN app.research_cases c ON c.id=p.research_case_id JOIN app.model_versions m ON m.id=p.model_version_id
          WHERE p.id=:id AND (c.owner_user_id=:uid OR :admin)''',id=prediction_id,uid=user['id'],admin=user['role']=='admin')
        if not result:raise APIError('RESOURCE_NOT_FOUND',404)
        return envelope(result)


@router.get('/predictions/{prediction_id}/explanation')
def prediction_explanation(prediction_id: UUID, user: Actor):
    record=prediction_history(prediction_id,user)['data']
    if not record['explanation_json']:raise APIError('EXPLANATION_NOT_READY',503)
    return envelope({'prediction_id':prediction_id,'model_version':record['model_version'],'feature_snapshot_id':record['feature_snapshot_id'],**record['explanation_json']})
