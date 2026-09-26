"""Apply one reviewed, immutable pilot-profile linking batch.

This command is intentionally narrow. It does not accept arbitrary users,
student codes, curricula, or cohorts from the command line.

Usage:
    python -m app.link_approved_pilot_profiles --profiles-json '[...]' --dry-run
    python -m app.link_approved_pilot_profiles --profiles-json '[...]' \
        --confirm LINK_APPROVED_PILOT_PROFILES
"""
from __future__ import annotations

import argparse
import json
import re

from app.store import one, run, transaction


CONFIRMATION = "LINK_APPROVED_PILOT_PROFILES"
CURRICULUM_CODE = "HTTT-UTT"
CURRICULUM_VERSION = "2024"
COHORT_CODE = "K75"
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
STUDENT_CODE_RE = re.compile(r"^PILOT-[A-Z0-9_-]{2,40}$")


def validate_profiles(profiles):
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 10:
        raise ValueError("PROFILES_MUST_CONTAIN_1_TO_10_ITEMS")
    normalized = []
    seen_users = set()
    seen_codes = set()
    for item in profiles:
        if not isinstance(item, dict) or set(item) != {"username", "student_code", "full_name"}:
            raise ValueError("PROFILE_FIELDS_INVALID")
        username = str(item["username"]).strip().lower()
        student_code = str(item["student_code"]).strip().upper()
        full_name = str(item["full_name"]).strip()
        if not USERNAME_RE.fullmatch(username) or not STUDENT_CODE_RE.fullmatch(student_code):
            raise ValueError("PROFILE_IDENTIFIER_INVALID")
        if not 1 <= len(full_name) <= 160:
            raise ValueError("PROFILE_NAME_INVALID")
        if username in seen_users or student_code in seen_codes:
            raise ValueError("PROFILE_DUPLICATE")
        seen_users.add(username)
        seen_codes.add(student_code)
        normalized.append((username, student_code, full_name))
    return tuple(normalized)


def apply_batch(profiles, *, confirmation: str | None = None, dry_run: bool = False):
    if not dry_run and confirmation != CONFIRMATION:
        raise ValueError(f"CONFIRM_REQUIRED: pass --confirm {CONFIRMATION}")

    profiles = validate_profiles(profiles)
    results = []
    with transaction() as db:
        curriculum = one(db, """SELECT id,code,version FROM app.curricula
            WHERE code=:code AND version=:version AND status='demo' FOR SHARE""",
            code=CURRICULUM_CODE, version=CURRICULUM_VERSION)
        if not curriculum:
            raise ValueError("CURRICULUM_NOT_FOUND: HTTT-UTT/2024")
        cohort = one(db, """SELECT id,code,curriculum_id FROM app.cohorts
            WHERE code=:code AND curriculum_id=:curriculum_id FOR SHARE""",
            code=COHORT_CODE, curriculum_id=curriculum["id"])
        if not cohort:
            raise ValueError("COHORT_NOT_FOUND: K75")

        # Validate the complete batch before the first write. A conflict rolls
        # back the whole transaction; partial linking is never committed.
        prepared = []
        for username, student_code, full_name in profiles:
            user = one(db, """SELECT id,username,role,is_active FROM app.users
                WHERE lower(username)=:username FOR UPDATE""", username=username)
            if not user:
                raise ValueError(f"USER_NOT_FOUND: {username}")
            if user["role"] != "student" or not user["is_active"]:
                raise ValueError(f"USER_NOT_ELIGIBLE: {username}")
            existing = one(db, """SELECT id,student_code,curriculum_id,cohort_id
                FROM app.students WHERE user_id=:user_id FOR UPDATE""", user_id=user["id"])
            if existing:
                exact = (existing["student_code"] == student_code and
                         existing["curriculum_id"] == curriculum["id"] and
                         existing["cohort_id"] == cohort["id"])
                if not exact:
                    raise ValueError(f"ACCOUNT_ALREADY_LINKED: {username}")
                prepared.append((user, student_code, full_name, "idempotent", existing["id"]))
                continue
            claimed = one(db, """SELECT user_id FROM app.students
                WHERE domain_id='demo_academic' AND student_code=:student_code FOR UPDATE""",
                student_code=student_code)
            if claimed:
                raise ValueError(f"STUDENT_CODE_ALREADY_LINKED: {student_code}")
            prepared.append((user, student_code, full_name, "ready", None))

        for user, student_code, full_name, status, student_id in prepared:
            if status == "ready" and not dry_run:
                student = one(db, """INSERT INTO app.students
                    (user_id,student_code,full_name,curriculum_id,cohort,cohort_id,domain_id,data_origin)
                    VALUES(:user_id,:student_code,:full_name,:curriculum_id,:cohort,:cohort_id,
                           'demo_academic','synthetic') RETURNING id""",
                    user_id=user["id"], student_code=student_code, full_name=full_name,
                    curriculum_id=curriculum["id"], cohort=cohort["code"], cohort_id=cohort["id"])
                student_id = student["id"]
                run(db, """INSERT INTO app.account_audit(actor_id,subject_id,action)
                    VALUES(NULL,:subject_id,'academic_profile_linked_approved_maintenance')""",
                    subject_id=user["id"])
                status = "linked"
            elif status == "ready":
                status = "would_link"
            results.append({"username": user["username"], "student_code": student_code,
                            "status": status, "student_id": str(student_id) if student_id else None})

    return {"dry_run": dry_run, "curriculum": "HTTT-UTT/2024",
            "cohort": "K75", "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-json", required=True,
                        help="JSON list with username, PILOT-* student_code, and full_name")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm")
    args = parser.parse_args()
    profiles = json.loads(args.profiles_json)
    print(json.dumps(apply_batch(profiles, confirmation=args.confirm, dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
