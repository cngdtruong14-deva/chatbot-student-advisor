"""Invite-only student accounts; no automatic synthetic student linking."""
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from pydantic import Field, field_validator
from fastapi import Request
from sqlalchemy.exc import IntegrityError
from app.api import Actor, DTO, APIError, envelope, router, require_role, rate_limit, same_origin
from app import responses as out
from app.security import password_hash, token_hash
from app.store import transaction, one, rows, run


class Registration(DTO):
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{3,32}$")
    password: str = Field(min_length=12, max_length=256)
    invite_code: str = Field(min_length=20, max_length=128)


class Recovery(DTO):
    code: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=12, max_length=256)


class PersonalProfile(DTO):
    display_name: str = Field(min_length=1, max_length=120)
    major: str = Field(default="", max_length=120)
    cohort: str = Field(default="", max_length=60)

    @field_validator("display_name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Blank name")
        return value.strip()

    @field_validator("major")
    @classmethod
    def trimmed_optional(cls, value):
        return value.strip()

    @field_validator("cohort")
    @classmethod
    def normalized_cohort(cls, value):
        return value.strip().upper()


class AcademicProfileLink(DTO):
    student_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str = Field(min_length=2, max_length=160)
    curriculum_id: UUID
    cohort_id: UUID
    confirmation: str = Field(pattern=r"^LINK_ACADEMIC_PROFILE$")

    @field_validator("student_code")
    @classmethod
    def normalized_code(cls, value):
        return value.strip().upper()

    @field_validator("full_name")
    @classmethod
    def normalized_name(cls, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Blank name")
        return value


def audit(db, actor, subject, action):
    run(db, "INSERT INTO app.account_audit(actor_id,subject_id,action) VALUES(:a,:s,:v)", a=actor, s=subject, v=action)


@router.get("/admin/accounts", response_model=out.Envelope[out.AdminAccountList])
def accounts(user: Actor, q: str = ""):
    """Admin-only account inventory with explicit academic-link state."""
    require_role(user, "admin")
    needle = f"%{q.strip().lower()}%"
    with transaction() as db:
        items = rows(db, """SELECT u.id,u.username,u.email,u.role,u.is_active,u.created_at,
              p.display_name,p.major AS self_reported_major,p.cohort AS self_reported_cohort,
              COALESCE(pt.revision,0) AS personal_transcript_revision,
              s.id AS student_id,s.student_code,s.full_name,s.curriculum_id,s.cohort_id,
              COALESCE(ch.code,s.cohort) AS cohort_code,c.code AS curriculum_code,
              c.version AS curriculum_version,c.major AS curriculum_major,
              COALESCE((SELECT count(*) FROM app.advisor_assignments aa WHERE aa.student_id=s.id),0) AS advisor_count
            FROM app.users u
            LEFT JOIN app.onboarding_profiles p ON p.user_id=u.id
            LEFT JOIN app.personal_transcripts pt ON pt.user_id=u.id
            LEFT JOIN app.students s ON s.user_id=u.id
            LEFT JOIN app.curricula c ON c.id=s.curriculum_id
            LEFT JOIN app.cohorts ch ON ch.id=s.cohort_id
            WHERE :q='%%' OR lower(COALESCE(u.username,'') || ' ' || u.email || ' ' ||
                  COALESCE(p.display_name,'') || ' ' || COALESCE(s.student_code,'') || ' ' ||
                  COALESCE(s.full_name,'')) LIKE :q
            ORDER BY CASE u.role WHEN 'admin' THEN 1 WHEN 'advisor' THEN 2 ELSE 3 END,
                     COALESCE(u.username,u.email),u.id LIMIT 250""", q=needle)
    return envelope({"items": items})


@router.get("/admin/cohorts", response_model=out.Envelope[out.CohortCatalog])
def admin_cohorts(user: Actor):
    require_role(user, "admin")
    with transaction() as db:
        items = rows(db, """SELECT ch.id,ch.code,ch.curriculum_id,c.code AS curriculum_code,
              c.version AS curriculum_version,c.major
            FROM app.cohorts ch JOIN app.curricula c ON c.id=ch.curriculum_id
            WHERE c.status='demo' ORDER BY c.major,c.version,ch.code""")
    return envelope({"items": items})


@router.get("/admin/account-audit", response_model=out.Envelope[out.AdminAccountAuditList])
def account_audit(user: Actor, limit: int = 50):
    require_role(user, "admin")
    limit = max(1, min(limit, 100))
    with transaction() as db:
        items = rows(db, """SELECT a.id,a.action,a.created_at,
              COALESCE(actor.username,actor.email) AS actor,
              COALESCE(subject.username,subject.email) AS subject
            FROM app.account_audit a
            LEFT JOIN app.users actor ON actor.id=a.actor_id
            LEFT JOIN app.users subject ON subject.id=a.subject_id
            ORDER BY a.created_at DESC,a.id DESC LIMIT :limit""", limit=limit)
    return envelope({"items": items})


@router.post("/admin/accounts/{user_id}/academic-profile", response_model=out.Envelope[out.AdminAcademicProfileLinkResult])
def academic_profile_link(user_id: UUID, body: AcademicProfileLink, user: Actor, request: Request):
    """Create one synthetic pilot academic profile; ownership is never transferred."""
    require_role(user, "admin")
    rate_limit(request, "academic_profile_link", 20)
    with transaction() as db:
        target = one(db, "SELECT id,role,is_active FROM app.users WHERE id=:id FOR UPDATE", id=user_id)
        if not target or target["role"] != "student":
            raise APIError("RESOURCE_NOT_FOUND", 404, "Không tìm thấy tài khoản sinh viên")
        if not target["is_active"]:
            raise APIError("ACCOUNT_INACTIVE", 409, "Không thể liên kết tài khoản đã khóa")
        curriculum = one(db, "SELECT id FROM app.curricula WHERE id=:id AND status='demo'", id=body.curriculum_id)
        cohort = one(db, "SELECT id,code,curriculum_id FROM app.cohorts WHERE id=:id", id=body.cohort_id)
        if not curriculum or not cohort or cohort["curriculum_id"] != curriculum["id"]:
            raise APIError("INVALID_ACADEMIC_PROFILE", 422, "Khóa không thuộc chương trình đã chọn")
        existing = one(db, "SELECT id,student_code,curriculum_id,cohort_id FROM app.students WHERE user_id=:id FOR UPDATE", id=user_id)
        if existing:
            exact = (existing["student_code"] == body.student_code and
                     existing["curriculum_id"] == body.curriculum_id and
                     existing["cohort_id"] == body.cohort_id)
            if not exact:
                raise APIError("ACCOUNT_ALREADY_LINKED", 409,
                               "Tài khoản đã liên kết hồ sơ khác; không cho phép chuyển hoặc ghi đè tự động")
            return envelope({"linked": True, "idempotent": True, "student_id": existing["id"],
                             "student_code": existing["student_code"], "data_origin": "synthetic"})
        claimed = one(db, "SELECT user_id FROM app.students WHERE domain_id='demo_academic' AND student_code=:code FOR UPDATE",
                      code=body.student_code)
        if claimed:
            raise APIError("STUDENT_CODE_ALREADY_LINKED", 409, "Mã sinh viên đã thuộc tài khoản khác")
        student = one(db, """INSERT INTO app.students
              (user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
            VALUES(:user_id,:student_code,:full_name,:curriculum_id,:cohort,:cohort_id,
                   'demo_academic','synthetic') RETURNING id,student_code""",
            user_id=user_id, student_code=body.student_code, full_name=body.full_name,
            curriculum_id=body.curriculum_id, cohort=cohort["code"], cohort_id=body.cohort_id)
        audit(db, user["id"], user_id, "academic_profile_linked")
    return envelope({"linked": True, "idempotent": False, "student_id": student["id"],
                     "student_code": student["student_code"], "data_origin": "synthetic"})


@router.post("/admin/account-invites", response_model=out.Envelope[out.OneTimeAccountCode])
def invite(user: Actor, request: Request):
    require_role(user, "admin")
    rate_limit(request, "invite", 10)
    code = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    with transaction() as db:
        one(db, """INSERT INTO app.pilot_invites(code_hash,created_by,expires_at)
          VALUES(:h,:u,:e) RETURNING id""", h=token_hash(code), u=user["id"], e=expires)
        audit(db, user["id"], None, "invite_created")
    return envelope({"code": code, "expires_at": expires, "display_once": True})


@router.post("/auth/register", response_model=out.Envelope[out.RegistrationResult])
def register(body: Registration, request: Request):
    same_origin(request)
    rate_limit(request, "register", 5)
    hashed = password_hash(body.password)
    try:
        with transaction() as db:
            invitation = one(db, """SELECT id FROM app.pilot_invites WHERE code_hash=:h
              AND consumed_by IS NULL AND expires_at>now() FOR UPDATE""", h=token_hash(body.invite_code))
            if not invitation:
                raise APIError("INVALID_INVITE", 422, "Mã mời không hợp lệ hoặc đã hết hạn")
            uid = uuid4()
            # Keep legacy email login intact; reserved non-deliverable internal alias.
            run(db, """INSERT INTO app.users(id,email,username,password_hash,role)
              VALUES(:id,:email,:username,:pw,'student')""", id=uid,
                email=f"{uid}@accounts.invalid", username=body.username.lower(), pw=hashed)
            run(db, "UPDATE app.pilot_invites SET consumed_by=:u,consumed_at=now() WHERE id=:i", u=uid, i=invitation["id"])
            audit(db, uid, uid, "registered")
    except IntegrityError:
        raise APIError("REGISTRATION_CONFLICT", 409, "Không thể dùng tên đăng nhập này")
    return envelope({"registered": True})


@router.post("/admin/accounts/{user_id}/recovery", response_model=out.Envelope[out.OneTimeAccountCode])
def recovery_issue(user_id: UUID, user: Actor, request: Request):
    require_role(user, "admin")
    rate_limit(request, "recovery_issue", 5)
    code = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=30)
    with transaction() as db:
        target = one(db, "SELECT id,role FROM app.users WHERE id=:id AND is_active FOR UPDATE", id=user_id)
        if not target or target["role"] != "student":
            raise APIError("RESOURCE_NOT_FOUND", 404)
        run(db, "UPDATE app.users SET auth_version=auth_version+1 WHERE id=:id", id=user_id)
        run(db, "UPDATE app.refresh_sessions SET revoked_at=now() WHERE user_id=:id AND revoked_at IS NULL", id=user_id)
        run(db, """INSERT INTO app.account_recovery(user_id,code_hash,expires_at,created_by)
          VALUES(:u,:h,:e,:a) ON CONFLICT(user_id) DO UPDATE SET
          code_hash=excluded.code_hash,expires_at=excluded.expires_at,created_by=excluded.created_by""",
            u=user_id, h=token_hash(code), e=expires, a=user["id"])
        audit(db, user["id"], user_id, "recovery_issued")
    return envelope({"code": code, "expires_at": expires, "display_once": True})


@router.post("/auth/recover", response_model=out.Envelope[out.RecoveryResult])
def recover(body: Recovery, request: Request):
    same_origin(request)
    rate_limit(request, "recover", 5)
    hashed = password_hash(body.password)
    with transaction() as db:
        candidate = one(db, "SELECT user_id FROM app.account_recovery WHERE code_hash=:h", h=token_hash(body.code))
        if not candidate:
            raise APIError("INVALID_RECOVERY", 422)
        target = one(db, "SELECT id FROM app.users WHERE id=:u AND is_active FOR UPDATE", u=candidate["user_id"])
        rec = one(db, "SELECT user_id FROM app.account_recovery WHERE code_hash=:h AND expires_at>now() FOR UPDATE", h=token_hash(body.code))
        if not rec or not target:
            raise APIError("INVALID_RECOVERY", 422)
        run(db, "UPDATE app.users SET password_hash=:p,auth_version=auth_version+1 WHERE id=:u", p=hashed, u=rec["user_id"])
        run(db, "UPDATE app.refresh_sessions SET revoked_at=now() WHERE user_id=:u AND revoked_at IS NULL", u=rec["user_id"])
        run(db, "DELETE FROM app.account_recovery WHERE user_id=:u", u=rec["user_id"])
        audit(db, rec["user_id"], rec["user_id"], "password_recovered")
    return envelope({"recovered": True})


@router.get("/account/profile", response_model=out.Envelope[out.PersonalAccountProfile | None])
def profile(user: Actor):
    require_role(user, "student")
    with transaction() as db:
        return envelope(one(db, "SELECT display_name,major,cohort,data_origin FROM app.onboarding_profiles WHERE user_id=:u", u=user["id"]))


@router.put("/account/profile", response_model=out.Envelope[out.ProfileSaveResult])
def profile_save(body: PersonalProfile, user: Actor):
    require_role(user, "student")
    with transaction() as db:
        if body.major:
            curriculum = one(db, "SELECT id FROM app.curricula WHERE major=:major AND status='demo' LIMIT 1",
                             major=body.major)
            if not curriculum:
                raise APIError("UNKNOWN_MAJOR", 422, "Hãy chọn một ngành có trong danh mục học vụ")
            if not one(db, """SELECT ch.id FROM app.cohorts ch
                  JOIN app.curricula c ON c.id=ch.curriculum_id
                WHERE ch.code=:code AND c.major=:major AND c.status='demo' LIMIT 1""",
                       code=body.cohort, major=body.major):
                raise APIError("UNKNOWN_COHORT", 422, "Hãy chọn một khóa thuộc đúng chương trình đã chọn")
        elif body.cohort:
            raise APIError("MAJOR_REQUIRED", 422, "Hãy chọn ngành trước khi chọn khóa")
        run(db, """INSERT INTO app.onboarding_profiles(user_id,display_name,major,cohort)
          VALUES(:u,:n,:m,:c) ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,
          major=excluded.major,cohort=excluded.cohort,updated_at=now()""",
            u=user["id"], n=body.display_name, m=body.major, c=body.cohort)
        audit(db, user["id"], user["id"], "profile_updated")
    return envelope({"saved": True, "data_origin": "self_reported"})
