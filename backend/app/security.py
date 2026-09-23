"""Local-only auth: scrypt passwords, short-lived JWTs, hashed rotating refresh sessions."""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
import jwt


def password_hash(password):
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12–256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.b64encode(salt + digest).decode()


def verify_password(password, encoded):
    if len(password) > 256:
        return False
    try:
        raw = base64.b64decode(encoded, validate=True)
        candidate = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
        return hmac.compare_digest(raw[16:], candidate)
    except (ValueError, TypeError):
        return False


def signing_key():
    key = os.environ.get("JWT_SECRET", "")
    if len(key) < 32:
        raise RuntimeError("AUTH_NOT_CONFIGURED")
    return key


def access_token(user_id, auth_version=0):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "ver": auth_version, "iat": now, "exp": now + timedelta(minutes=15),
                       "iss": "student-advisor", "aud": "student-advisor-web"}, signing_key(), algorithm="HS256")


def decode_token(token):
    return jwt.decode(token, signing_key(), algorithms=["HS256"], issuer="student-advisor",
                      audience="student-advisor-web", options={"require": ["sub", "iat", "exp", "iss", "aud"]})


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
