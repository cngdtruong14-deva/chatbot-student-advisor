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
from app.store import transaction, one, run


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

    @field_validator("major", "cohort")
    @classmethod
    def trimmed_optional(cls, value):
        return value.strip()


def audit(db, actor, subject, action):
    run(db, "INSERT INTO app.account_audit(actor_id,subject_id,action) VALUES(:a,:s,:v)", a=actor, s=subject, v=action)


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
        if body.major and not one(
            db,
            "SELECT id FROM app.curricula WHERE major=:major AND status='demo' LIMIT 1",
            major=body.major,
        ):
            raise APIError("UNKNOWN_MAJOR", 422, "Hãy chọn một ngành có trong danh mục học vụ")
        run(db, """INSERT INTO app.onboarding_profiles(user_id,display_name,major,cohort)
          VALUES(:u,:n,:m,:c) ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name,
          major=excluded.major,cohort=excluded.cohort,updated_at=now()""",
            u=user["id"], n=body.display_name, m=body.major, c=body.cohort)
        audit(db, user["id"], user["id"], "profile_updated")
    return envelope({"saved": True, "data_origin": "self_reported"})
