"""
Create a school and its first head teacher: `tasks newschool`.

There is no open sign-up, by design - a head teacher's staff list is the gate
for every account, password or Google. That leaves the first head teacher of
a new school with no one to add them, and until now the only way in was the
demonstration data. This is that first step, run by whoever operates the
server, once per school.

The head teacher is created exactly as the staff screen creates a teacher:
no usable password, and a one-time setup code. The operator never chooses or
sees a password, and the code is printed once. From there the head teacher
sets a password at "Set up your account" (or signs in with Google using the
same email) and adds their own staff and classes.

    tasks newschool
    tasks newschool --school "Kilimani Primary" --type public \
        --head-name "Wanjiru Kamau" --head-email wanjiru@kilimani.ac.ke

Asks for anything not given. Refuses an email that already has an account
and a school name that already exists, so running it twice by mistake does
not make a second school.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import ensure_extensions, get_engine, get_session_factory
from .models import Base, School, Teacher
from .security import (
    ROLE_SCHOOL_ADMIN,
    SETUP_CODE_TTL_DAYS,
    UNUSABLE_PASSWORD,
    hash_password,
    new_setup_code,
    normalise_code,
    normalise_email,
    setup_expiry,
)

SCHOOL_TYPES = ("public", "private")
_EMAIL = TypeAdapter(EmailStr)


class Refused(ValueError):
    """A reason, in words, that the school was not created."""


@dataclass(frozen=True)
class Created:
    school: School
    head: Teacher
    setup_code: str


def create_school(
    session: Session,
    school_name: str,
    school_type: str,
    head_name: str,
    head_email: str,
) -> Created:
    """The school, its head teacher and a one-time code, or Refused."""
    school_name = " ".join(school_name.split())
    head_name = " ".join(head_name.split())
    school_type = school_type.strip().lower()

    if len(school_name) < 3:
        raise Refused("The school name is too short.")
    if len(school_name) > 200:
        raise Refused("The school name is longer than 200 characters.")
    if school_type not in SCHOOL_TYPES:
        raise Refused(f"The school type must be one of: {', '.join(SCHOOL_TYPES)}.")
    if len(head_name) < 2:
        raise Refused("The head teacher's name is too short.")
    if len(head_name) > 200:
        raise Refused("The head teacher's name is longer than 200 characters.")
    try:
        email = normalise_email(_EMAIL.validate_python(head_email.strip()))
    except ValidationError:
        raise Refused(f"{head_email!r} is not an email address.") from None

    if session.scalar(select(Teacher).where(Teacher.email == email)) is not None:
        raise Refused(f"{email} already has an account.")
    same_name = session.scalar(
        select(School).where(func.lower(School.name) == school_name.lower())
    )
    if same_name is not None:
        raise Refused(f"A school called {same_name.name!r} already exists.")

    school = School(name=school_name, type=school_type)
    session.add(school)
    session.flush()

    code = new_setup_code()
    head = Teacher(
        name=head_name,
        email=email,
        role=ROLE_SCHOOL_ADMIN,
        school_id=school.school_id,
        password_hash=UNUSABLE_PASSWORD,
        setup_code_hash=hash_password(normalise_code(code)),
        setup_code_expires_at=setup_expiry(),
    )
    session.add(head)
    session.commit()
    return Created(school=school, head=head, setup_code=code)


def prepare_schema() -> None:
    """Safe on a database that already has tables: create_all only adds
    what is missing, so a fresh server needs no separate step first."""
    ensure_extensions()
    Base.metadata.create_all(get_engine())


def _ask(prompt: str, given: str | None) -> str:
    if given is not None:
        return given
    try:
        return input(f"{prompt}: ")
    except EOFError:
        raise Refused(f"No {prompt.lower()} given.") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tasks newschool",
        description="Create a school and its first head teacher, with a one-time setup code.",
    )
    ap.add_argument("--school", help="the school's name")
    ap.add_argument("--type", choices=SCHOOL_TYPES, help="public or private")
    ap.add_argument("--head-name", help="the head teacher's full name")
    ap.add_argument("--head-email", help="the email the head teacher will sign in with")
    args = ap.parse_args(argv)

    try:
        school_name = _ask("School name", args.school)
        school_type = _ask("Type (public / private)", args.type)
        head_name = _ask("Head teacher's name", args.head_name)
        head_email = _ask("Head teacher's email", args.head_email)

        prepare_schema()
        with get_session_factory()() as session:
            done = create_school(session, school_name, school_type, head_name, head_email)
    except Refused as why:
        print(f"Not created. {why}", file=sys.stderr)
        return 1

    print()
    print(f"Created {done.school.name} ({done.school.type}).")
    print(f"Head teacher: {done.head.name} <{done.head.email}>")
    print()
    print(f"    Setup code:  {done.setup_code}")
    print()
    print("Shown once and not stored readably - write it down or pass it on now.")
    print(f"It works once and expires in {SETUP_CODE_TTL_DAYS} days. The head teacher")
    print("opens the app, chooses \"Set up your account\", and enters their email,")
    print("this code and a password of their own. Or they sign in with Google using")
    print("the same email. Then they add their teachers and classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
