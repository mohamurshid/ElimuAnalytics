"""
Authentication endpoints and dependencies.

Login takes JSON rather than an OAuth2 form, which keeps the dependency list to
PyJWT and bcrypt. The bearer token carries the teacher's id and role; every
protected route resolves it back to a Teacher row rather than trusting the
claim, so a role changed in the database takes effect on the next request
rather than when the token expires.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Teacher
from .security import (
    ROLE_SCHOOL_ADMIN,
    create_token,
    role_at_least,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str


class ProfileResponse(BaseModel):
    teacher_id: str
    name: str
    email: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    teacher = session.scalar(select(Teacher).where(Teacher.email == body.email))
    # One message for both "no such account" and "wrong password": distinguishing
    # them tells an attacker which addresses are registered.
    if teacher is None or not verify_password(body.password, teacher.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_token(teacher.teacher_id, teacher.role, teacher.email),
        role=teacher.role,
        name=teacher.name,
    )


def current_teacher(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> Teacher:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    teacher = session.get(Teacher, uuid.UUID(payload["sub"]))
    if teacher is None:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return teacher


def decode(token: str) -> dict:
    from .security import decode_token

    return decode_token(token)


def require_role(minimum: str):
    """Dependency factory: `Depends(require_role(ROLE_SCHOOL_ADMIN))`."""

    def dependency(teacher: Teacher = Depends(current_teacher)) -> Teacher:
        if not role_at_least(teacher.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum} or higher; this account is {teacher.role}",
            )
        return teacher

    return dependency


require_school_admin = require_role(ROLE_SCHOOL_ADMIN)


@router.get("/me", response_model=ProfileResponse)
def me(teacher: Teacher = Depends(current_teacher)) -> ProfileResponse:
    return ProfileResponse(
        teacher_id=str(teacher.teacher_id),
        name=teacher.name,
        email=teacher.email,
        role=teacher.role,
    )
