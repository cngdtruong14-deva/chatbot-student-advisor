"""Administrative password reset utility for local development and demo accounts."""
from __future__ import annotations

import argparse
import getpass
import sys

from app.security import password_hash
from app.store import transaction, one, rows, run

DEMO_EMAILS = [
    "student@demo.local",
    "student2@demo.local",
    "advisor@demo.local",
    "admin@demo.local",
]


def update_user_password(email: str, password: str) -> bool:
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12–256 characters")
    encoded = password_hash(password)
    with transaction() as db:
        user = one(db, "SELECT id, email, role FROM app.users WHERE email=:email", email=email.strip().lower())
        if not user:
            return False
        run(db, "UPDATE app.users SET password_hash=:hash, is_active=true WHERE id=:id", hash=encoded, id=user["id"])
        run(db, "UPDATE app.refresh_sessions SET revoked_at=now() WHERE user_id=:id AND revoked_at IS NULL", id=user["id"])
    return True


def main():
    parser = argparse.ArgumentParser(description="Reset user password in local PostgreSQL database.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--email", help="Target user email (e.g. student@demo.local)")
    group.add_argument("--all-demo", action="store_true", help="Reset all 4 demo accounts (student, student2, advisor, admin)")
    parser.add_argument("--password", help="New password (12-256 chars). If omitted, prompts securely.")

    args = parser.parse_args()
    pw = args.password
    if not pw:
        pw = getpass.getpass("Nhập mật khẩu mới (12–256 ký tự): ")
        pw_confirm = getpass.getpass("Xác nhận lại mật khẩu: ")
        if pw != pw_confirm:
            print("Lỗi: Mật khẩu xác nhận không khớp!", file=sys.stderr)
            sys.exit(1)

    try:
        if args.all_demo:
            success_count = 0
            for email in DEMO_EMAILS:
                if update_user_password(email, pw):
                    success_count += 1
                    print(f"Đã cập nhật mật khẩu cho: {email}")
                else:
                    print(f"Bỏ qua (không tìm thấy): {email}")
            print(f"Hoàn thành cập nhật cho {success_count}/{len(DEMO_EMAILS)} tài khoản demo.")
        else:
            if update_user_password(args.email, pw):
                print(f"Thành công: Đã cập nhật mật khẩu cho {args.email}")
            else:
                print(f"Lỗi: Không tìm thấy người dùng với email '{args.email}'", file=sys.stderr)
                sys.exit(1)
    except ValueError as exc:
        print(f"Lỗi hợp lệ: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
