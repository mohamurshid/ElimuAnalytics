"""
Authentication endpoints and dependencies.

Login takes JSON rather than an OAuth2 form, which keeps the dependency list to
PyJWT and bcrypt. The bearer token carries the teacher's id and role; every
protected route resolves it back to a Teacher row rather than trusting the
claim, so a role changed in the database takes effect on the next request
rather than when the token expires.

**Two tokens, with different jobs.** The access token is a short-lived JWT
returned in the response body, for the browser to hold in memory. The refresh
token is a long-lived opaque string in an httpOnly cookie, which JavaScript
cannot read at all.

The split exists because the two requirements conflict. A credential the page
can read is a credential an injected script can steal; a credential the page
cannot read cannot be attached to ordinary API calls. So the readable one is
made short-lived and disposable, and the durable one is locked away in a
cookie, revocable, and used for nothing but minting replacements.

**Rotation and reuse detection.** Every refresh issues a new token and retires
the old one. A retired token presented again is either a client replaying it
or an attacker using a copy, and the server cannot tell which - so it revokes
the entire family and forces a fresh sign-in. That turns a stolen refresh
token from indefinite access into, at worst, one extra session that ends the
moment the real teacher next refreshes.

**CSRF.** The refresh endpoint acts on a cookie the browser attaches
automatically, so it would otherwise be triggerable from any site the teacher
visits. Two defences: `SameSite` on the cookie, and an `Origin` check on the
request. The second matters because a cross-site deployment has to weaken the
first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import throttle
from .db import get_session
from .models import RefreshToken, Teacher
from .security import (
    ALLOWED_ORIGINS,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    REFRESH_TTL_DAYS,
    ROLE_SCHOOL_ADMIN,
    create_token,
    hash_refresh_token,
    new_refresh_token,
    refresh_expiry,
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
    # Shown on the profile page. Every query is already scoped to this
    # school, so a teacher seeing its name is being told what they can see,
    # not given anything new.
    school: str


def _issue_refresh(
    session: Session, response: Response, teacher: Teacher, family_id: uuid.UUID | None
) -> None:
    """Mint a refresh token, store its hash, and set the cookie."""
    raw = new_refresh_token()
    session.add(
        RefreshToken(
            teacher_id=teacher.teacher_id,
            token_hash=hash_refresh_token(raw),
            family_id=family_id or uuid.uuid4(),
            expires_at=refresh_expiry(),
        )
    )
    session.commit()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw,
        httponly=True,          # unreadable by any script on the page
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=REFRESH_TTL_DAYS * 24 * 60 * 60,
    )


def _revoke_family(session: Session, family_id: uuid.UUID) -> int:
    tokens = list(
        session.scalars(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked.is_(False),
            )
        )
    )
    for t in tokens:
        t.revoked = True
    session.commit()
    return len(tokens)


def _check_origin(request: Request) -> None:
    """Refuse a cross-site refresh.

    The browser attaches the cookie to any request to this endpoint, including
    one triggered by a page the teacher merely visited. `Origin` is set by the
    browser and cannot be forged by page script, so checking it is sufficient.
    A request without an Origin header is not a browser's cross-site form or
    fetch, so it is allowed through.

    **The application's own origin always passes.** Browsers send `Origin` on
    same-origin POST requests as well as cross-origin ones, so a check against
    a configured allowlist alone rejects the application's own page unless
    that page's address happens to be in the list. It is self-evidently not
    CSRF for a page to call its own API, and requiring every deployment to
    remember to allowlist itself is a trap - one this project fell into: the
    demonstration page at :8000 was refused because the list held only the
    frontend's :3000.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    same_origin = str(request.base_url).rstrip("/")
    if origin == same_origin or origin in ALLOWED_ORIGINS:
        return
    raise HTTPException(status_code=403, detail="Cross-origin refresh refused")


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    key = throttle.key_for(body.email, request)

    # Checked before the password, deliberately. Verifying first and letting a
    # correct password through would waive the limit on exactly the attempt
    # that matters - an attacker's successful guess.
    wait = throttle.retry_after(key)
    if wait is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )

    teacher = session.scalar(select(Teacher).where(Teacher.email == body.email))
    # One message for both "no such account" and "wrong password": distinguishing
    # them tells an attacker which addresses are registered.
    if teacher is None or not verify_password(body.password, teacher.password_hash):
        throttle.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    throttle.clear(key)
    _issue_refresh(session, response, teacher, family_id=None)
    return TokenResponse(
        access_token=create_token(teacher.teacher_id, teacher.role, teacher.email),
        role=teacher.role,
        name=teacher.name,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    """Exchange the refresh cookie for a new access token, and rotate it."""
    _check_origin(request)

    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token")

    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    )
    if stored is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.revoked:
        # A retired token has been presented again. Either the client replayed
        # it or someone else holds a copy, and there is no way to tell which,
        # so the whole family goes.
        _revoke_family(session, stored.family_id)
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        raise HTTPException(
            status_code=401,
            detail="This session was ended because a retired token was reused. Sign in again.",
        )

    expires_at = stored.expires_at
    if expires_at.tzinfo is None:  # SQLite returns naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        stored.revoked = True
        session.commit()
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    teacher = session.get(Teacher, stored.teacher_id)
    if teacher is None:
        raise HTTPException(status_code=401, detail="Account no longer exists")

    # Rotate: this one is spent the moment it is used.
    stored.revoked = True
    session.commit()
    _issue_refresh(session, response, teacher, family_id=stored.family_id)

    return TokenResponse(
        access_token=create_token(teacher.teacher_id, teacher.role, teacher.email),
        role=teacher.role,
        name=teacher.name,
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    """End the session everywhere it could be resumed.

    Takes no access token: a teacher whose access token has already expired
    must still be able to log out, and the cookie is the thing being revoked.
    """
    raw = request.cookies.get(REFRESH_COOKIE)
    revoked = 0
    if raw:
        stored = session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
        )
        if stored is not None:
            revoked = _revoke_family(session, stored.family_id)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return {"signed_out": True, "tokens_revoked": revoked}


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
        school=teacher.school.name if teacher.school else "",
    )
