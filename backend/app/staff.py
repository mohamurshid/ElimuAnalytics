"""
A head teacher's staff list: adding teachers, codes, roles, deactivation.

Agreed 21 October, before Google sign-in (planned after the quiz work):

  * a head teacher adds a teacher by name and email; the app shows a
    one-time setup code ONCE, for the head to pass on; the teacher sets
    their own password with it (auth.setup_account). The head never knows
    the password
  * a teacher who forgets their password gets a new code the same way.
    Issuing one signs the teacher out everywhere and their old password
    stops working, so a code given to the wrong person cannot be used
    alongside the real teacher's session
  * a head teacher can rename, change an email, change a role, deactivate
    and reactivate. Deactivating signs the teacher out everywhere; their
    classes and records stay
  * a school always keeps at least one active head teacher: the last one
    cannot be demoted or deactivated, or nobody could manage the school

Everything is scoped to the head teacher's own school, and another school's
teacher answers 404, as everywhere else.

**Ready for Google sign-in.** This list is the gate: OAuth will only let in
an email that a head teacher has added here. An account added here and
never given a password is exactly what a Google-only teacher looks like.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import end_sessions, require_school_admin
from .db import get_session
from .models import Teacher
from .security import (
    ROLE_SCHOOL_ADMIN,
    ROLE_TEACHER,
    UNUSABLE_PASSWORD,
    hash_password,
    new_setup_code,
    normalise_code,
    normalise_email,
    setup_expiry,
)

router = APIRouter(prefix="/api/staff", tags=["staff"])

Role = Literal["teacher", "school_admin"]


class StaffCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    role: Role = ROLE_TEACHER


class StaffUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    role: Role | None = None


class StaffOut(BaseModel):
    teacher_id: str
    name: str
    email: str
    role: str
    is_active: bool
    # "active": has a password. "invited": waiting to use a setup code.
    # "deactivated". One word for the screen to show.
    status: str
    setup_code_expires_at: str | None
    is_you: bool


class WithCode(StaffOut):
    """Returned once, when a code is made. Only its hash is stored, so this
    is the only time anyone - including the server - can read it."""

    setup_code: str


def _status(t: Teacher) -> str:
    if not t.is_active:
        return "deactivated"
    if t.setup_code_hash is not None:
        return "invited"
    return "active"


def _out(t: Teacher, me: Teacher) -> StaffOut:
    return StaffOut(
        teacher_id=str(t.teacher_id), name=t.name, email=t.email, role=t.role,
        is_active=t.is_active, status=_status(t),
        setup_code_expires_at=t.setup_code_expires_at.isoformat()
        if t.setup_code_expires_at else None,
        is_you=t.teacher_id == me.teacher_id,
    )


def _with_code(t: Teacher, me: Teacher, code: str) -> WithCode:
    return WithCode(**_out(t, me).model_dump(), setup_code=code)


def _member(session: Session, teacher_id: uuid.UUID, me: Teacher) -> Teacher:
    t = session.get(Teacher, teacher_id)
    if t is None or t.school_id != me.school_id:
        raise HTTPException(status_code=404, detail="No such teacher at your school")
    return t


def _active_heads(session: Session, school_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.count()).select_from(Teacher).where(
            Teacher.school_id == school_id,
            Teacher.role == ROLE_SCHOOL_ADMIN,
            Teacher.is_active.is_(True),
        )
    ) or 0


def _keep_a_head(session: Session, t: Teacher) -> None:
    if t.role == ROLE_SCHOOL_ADMIN and t.is_active and _active_heads(session, t.school_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail="A school needs at least one head teacher. Make someone else head "
            "teacher first.",
        )


def _issue_code(session: Session, t: Teacher) -> str:
    """A fresh code. The old password stops working and every session ends,
    so the code is the only way in until it is used."""
    code = new_setup_code()
    t.setup_code_hash = hash_password(normalise_code(code))
    t.setup_code_expires_at = setup_expiry()
    t.password_hash = UNUSABLE_PASSWORD
    end_sessions(session, t)
    return code


def _email_free(session: Session, email: str, except_id: uuid.UUID | None = None) -> None:
    other = session.scalar(select(Teacher).where(Teacher.email == email))
    if other is not None and other.teacher_id != except_id:
        raise HTTPException(status_code=409, detail="That email already has an account.")


@router.get("", response_model=list[StaffOut])
def list_staff(
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> list[StaffOut]:
    staff = session.scalars(
        select(Teacher).where(Teacher.school_id == me.school_id).order_by(Teacher.name)
    )
    return [_out(t, me) for t in staff]


@router.post("", response_model=WithCode, status_code=201)
def add_teacher(
    body: StaffCreate,
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> WithCode:
    email = normalise_email(body.email)
    _email_free(session, email)
    t = Teacher(
        name=body.name.strip(), email=email, role=body.role,
        school_id=me.school_id, password_hash=UNUSABLE_PASSWORD,
    )
    session.add(t)
    session.flush()
    code = _issue_code(session, t)
    session.commit()
    return _with_code(t, me, code)


@router.patch("/{teacher_id}", response_model=StaffOut)
def update_teacher(
    teacher_id: uuid.UUID,
    body: StaffUpdate,
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> StaffOut:
    t = _member(session, teacher_id, me)
    if body.name is not None:
        t.name = body.name.strip()
    if body.email is not None:
        email = normalise_email(body.email)
        _email_free(session, email, except_id=t.teacher_id)
        t.email = email
    if body.role is not None and body.role != t.role:
        if body.role != ROLE_SCHOOL_ADMIN:
            _keep_a_head(session, t)
        t.role = body.role
    session.commit()
    return _out(t, me)


@router.post("/{teacher_id}/setup-code", response_model=WithCode)
def new_code(
    teacher_id: uuid.UUID,
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> WithCode:
    """For a teacher who has forgotten their password, or whose code expired."""
    t = _member(session, teacher_id, me)
    if t.teacher_id == me.teacher_id:
        raise HTTPException(
            status_code=409,
            detail="Change your own password on your profile page instead.",
        )
    if not t.is_active:
        raise HTTPException(status_code=409, detail="Reactivate this account first.")
    code = _issue_code(session, t)
    session.commit()
    return _with_code(t, me, code)


@router.post("/{teacher_id}/deactivate", response_model=StaffOut)
def deactivate(
    teacher_id: uuid.UUID,
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> StaffOut:
    t = _member(session, teacher_id, me)
    if t.teacher_id == me.teacher_id:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
    _keep_a_head(session, t)
    t.is_active = False
    end_sessions(session, t)
    session.commit()
    return _out(t, me)


@router.post("/{teacher_id}/reactivate", response_model=StaffOut)
def reactivate(
    teacher_id: uuid.UUID,
    session: Session = Depends(get_session),
    me: Teacher = Depends(require_school_admin),
) -> StaffOut:
    t = _member(session, teacher_id, me)
    t.is_active = True
    session.commit()
    return _out(t, me)
