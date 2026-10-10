"""
Password hashing and JWT issuing.

Chapter 3 specifies bcrypt for password storage and three roles: teacher,
school administrator, system administrator.

The signing secret comes from JWT_SECRET. There is a development default so
the project runs out of the box, and `secret_is_default()` exists so the
application can refuse to start with it in anything resembling production - a
default signing key is not a weak secret, it is a published one.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

ALGORITHM = "HS256"
# Shortened from 60 minutes once refresh tokens existed. A stolen access token
# is usable until it expires and cannot be withdrawn, so the window should be
# only as long as the inconvenience of renewing it justifies.
TOKEN_TTL_MINUTES = int(os.environ.get("JWT_TTL_MINUTES", "15"))

# The refresh token outlives the access token by design: it is revocable, so a
# long life costs little, and it is what spares a teacher a sign-in every
# fifteen minutes.
REFRESH_TTL_DAYS = int(os.environ.get("REFRESH_TTL_DAYS", "14"))
REFRESH_COOKIE = "elimu_refresh"
# The cookie is scoped to the auth routes: nothing else needs it, so nothing
# else should receive it.
REFRESH_COOKIE_PATH = "/api/auth"

# Secure must be on wherever HTTPS is available, and cannot be on over plain
# HTTP in development or the browser silently drops the cookie.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
# Lax is enough while the interface and the API share a registrable domain,
# which includes two ports on localhost. A cross-site deployment needs "none"
# -- and then the Origin check in auth.py is doing the CSRF work alone.
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").lower()

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]
# At least 32 bytes: PyJWT warns below that for HS256 (RFC 7518 3.2), and a
# development default that emits a security warning teaches the wrong habit.
DEV_SECRET = "elimu-analytics-development-only-secret-change-me"  # noqa: S105

ROLE_TEACHER = "teacher"
ROLE_SCHOOL_ADMIN = "school_admin"
ROLE_SYSTEM_ADMIN = "system_admin"
ROLES = (ROLE_TEACHER, ROLE_SCHOOL_ADMIN, ROLE_SYSTEM_ADMIN)

# Ascending privilege. A check is "role is at least X", never an equality test,
# so adding a role later does not mean revisiting every endpoint.
ROLE_RANK = {ROLE_TEACHER: 1, ROLE_SCHOOL_ADMIN: 2, ROLE_SYSTEM_ADMIN: 3}


def secret() -> str:
    return os.environ.get("JWT_SECRET", DEV_SECRET)


def secret_is_default() -> bool:
    return secret() == DEV_SECRET


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # A malformed or placeholder hash must fail closed, not raise.
        return False


def create_token(teacher_id: uuid.UUID, role: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(teacher_id),
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on anything invalid, including expiry."""
    return jwt.decode(token, secret(), algorithms=[ALGORITHM])


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


# --- refresh tokens --------------------------------------------------------
# Opaque and random, not a JWT: a JWT is valid until it expires and cannot be
# withdrawn, and withdrawal is the whole reason this token is separate.


def new_refresh_token() -> str:
    """256 bits from the OS entropy pool, URL-safe."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw: str) -> str:
    """SHA-256, not bcrypt.

    The input is 256 bits of randomness rather than a guessable password, so
    there is nothing for a slow hash to defend against - and the lookup
    happens on every refresh, against an indexed column.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS)
