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

import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = int(os.environ.get("JWT_TTL_MINUTES", "60"))
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
