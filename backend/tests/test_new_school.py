"""
`tasks newschool`: the first head teacher of a new school.

What it must guarantee:

  * the school and head teacher are created exactly as the staff screen
    creates a teacher - no usable password, a one-time code stored hashed -
    and that code really does open the account
  * the new school is separate: its head teacher sees only their own staff
  * running it twice by mistake, or with a typo, changes nothing
"""

from __future__ import annotations

import pytest
from app import new_school
from app.db import get_session
from app.main import app
from app.models import School, Teacher
from app.new_school import Refused, create_school
from app.security import ROLE_SCHOOL_ADMIN, UNUSABLE_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from .test_repository import session  # noqa: F401 - pytest fixture


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make(session, **change):  # noqa: F811
    args = {"school_name": "Kilimani Primary", "school_type": "public",
            "head_name": "Wanjiru Kamau", "head_email": "Wanjiru@Kilimani.ac.ke"}
    return create_school(session, **{**args, **change})


def test_a_school_and_its_head_teacher_are_created(session):  # noqa: F811
    done = make(session)
    assert done.school.name == "Kilimani Primary"
    assert done.head.role == ROLE_SCHOOL_ADMIN
    assert done.head.school_id == done.school.school_id
    assert done.head.email == "wanjiru@kilimani.ac.ke"  # stored as every email is


def test_the_head_has_no_password_and_the_code_is_not_stored_readably(session):  # noqa: F811
    done = make(session)
    assert done.head.password_hash == UNUSABLE_PASSWORD
    assert done.head.setup_code_hash is not None
    assert done.setup_code.replace("-", "") not in done.head.setup_code_hash
    assert done.head.setup_code_expires_at is not None


def test_the_code_opens_the_account_and_the_school_is_separate(client, session):  # noqa: F811
    done = make(session)
    r = client.post("/api/auth/setup", json={"email": "wanjiru@kilimani.ac.ke",
                                              "code": done.setup_code.lower(),
                                              "password": "a-new-password"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    staff = client.get("/api/staff", headers=headers)
    assert staff.status_code == 200
    assert [m["email"] for m in staff.json()] == ["wanjiru@kilimani.ac.ke"]
    assert client.get("/api/classrooms", headers=headers).json() == []


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"school_name": "test school"}, "already exists"),
        ({"school_type": "boarding"}, "must be one of"),
        ({"head_email": "not-an-email"}, "not an email address"),
        ({"school_name": "  K "}, "too short"),
        ({"head_name": "W"}, "too short"),
    ],
)
def test_a_mistake_is_refused_and_changes_nothing(session, change, reason):  # noqa: F811
    schools = session.scalar(select(func.count()).select_from(School))
    teachers = session.scalar(select(func.count()).select_from(Teacher))
    with pytest.raises(Refused, match=reason):
        make(session, **change)
    session.rollback()
    assert session.scalar(select(func.count()).select_from(School)) == schools
    assert session.scalar(select(func.count()).select_from(Teacher)) == teachers


def test_an_email_with_an_account_is_refused_whatever_its_case(session):  # noqa: F811
    make(session)
    with pytest.raises(Refused, match="already has an account"):
        make(session, school_name="Another Primary", head_email="WANJIRU@kilimani.ac.ke")


def test_running_it_twice_makes_one_school(session):  # noqa: F811
    make(session)
    with pytest.raises(Refused):
        make(session, head_email="someone.else@kilimani.ac.ke")
    assert session.scalar(
        select(func.count()).select_from(School).where(School.name == "Kilimani Primary")
    ) == 1


@pytest.fixture
def command(session, monkeypatch):  # noqa: F811
    """main() against the test database instead of the server's."""
    monkeypatch.setattr(new_school, "prepare_schema", lambda: None)
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(new_school, "get_session_factory", lambda: factory)
    return new_school.main


def test_the_command_prints_the_code_once(command, capsys):
    status = command(["--school", "Kilimani Primary", "--type", "public",
                      "--head-name", "Wanjiru Kamau", "--head-email", "wanjiru@kilimani.ac.ke"])
    out = capsys.readouterr().out
    assert status == 0
    assert "Setup code:" in out and "Set up your account" in out


def test_the_command_asks_for_what_it_was_not_given(command, monkeypatch, capsys):
    answers = iter(["Kilimani Primary", "private", "Wanjiru Kamau", "wanjiru@kilimani.ac.ke"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert command([]) == 0
    assert "Created Kilimani Primary (private)" in capsys.readouterr().out


def test_the_command_reports_a_refusal_and_fails(command, capsys):
    status = command(["--school", "Test School", "--type", "public",
                      "--head-name", "Wanjiru Kamau", "--head-email", "w@k.ke"])
    assert status == 1
    assert "Not created" in capsys.readouterr().err
