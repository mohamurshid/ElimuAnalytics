"""
Teacher accounts: added by a head teacher, set up with a one-time code.

The properties that matter, each tested directly:

  * the setup code works once, expires, is throttled, and is never stored
    readable - and every way it can be wrong gets the same answer
  * ending sessions means ENDED: after a new code, a password change, "sign
    out everywhere" or deactivation, an access token issued earlier is
    refused at once, not when it happens to expire
  * a school always keeps an active head teacher
  * everything is scoped to the head teacher's own school
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from app.db import get_session
from app.main import app
from app.models import School, Teacher
from app.security import ROLE_SCHOOL_ADMIN, create_token, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

HEAD_PASSWORD = "head-password-1"


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def head(session) -> Teacher:  # noqa: F811
    existing = session.scalar(select(Teacher))
    h = Teacher(name="Head", email="head@school.ke", password_hash=hash_password(HEAD_PASSWORD),
                role=ROLE_SCHOOL_ADMIN, school_id=existing.school_id)
    session.add(h)
    session.commit()
    return h


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def held_token(session, t: Teacher) -> dict:  # noqa: F811
    """The token a device holds right now: issued under the account's
    current session version. Kept, then presented after sessions are ended."""
    session.refresh(t)
    token = create_token(t.teacher_id, t.role, t.email, t.session_version)
    return {"Authorization": f"Bearer {token}"}


def add(client, head, email="Wanjiru@School.KE", name="Wanjiru K.", role="teacher"):
    return client.post("/api/staff", json={"name": name, "email": email, "role": role},
                       headers=auth(head))


def setup(client, email, code, password="a-new-password"):
    return client.post("/api/auth/setup", json={"email": email, "code": code,
                                                 "password": password})


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def me(client, headers):
    return client.get("/api/auth/me", headers=headers)


# --- adding and setting up -------------------------------------------------
def test_a_head_teacher_adds_a_teacher_and_sees_the_code_once(client, session, head):  # noqa: F811
    r = add(client, head)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "wanjiru@school.ke"  # stored in lower case
    assert body["status"] == "invited"
    code = body["setup_code"]
    assert len(code) == 9 and code[4] == "-"
    stored = session.scalar(select(Teacher).where(Teacher.email == "wanjiru@school.ke"))
    assert code not in (stored.setup_code_hash or "")  # only a hash is kept
    listed = client.get("/api/staff", headers=auth(head)).json()
    assert all("setup_code" not in row for row in listed)


def test_the_code_sets_a_password_once_and_signs_the_teacher_in(client, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    assert login(client, "wanjiru@school.ke", "anything").status_code == 401

    r = setup(client, "WANJIRU@school.ke", code.lower().replace("-", " "))  # forgiving input
    assert r.status_code == 200 and r.json()["access_token"]
    assert login(client, "wanjiru@school.ke", "a-new-password").status_code == 200
    assert setup(client, "wanjiru@school.ke", code).status_code == 400  # used up


def test_every_wrong_code_gets_the_same_answer(client, session, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    wrong = setup(client, "wanjiru@school.ke", "AAAA-AAAA")
    unknown = setup(client, "nobody@school.ke", code)
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json()["detail"] == unknown.json()["detail"]

    t = session.scalar(select(Teacher).where(Teacher.email == "wanjiru@school.ke"))
    t.setup_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.commit()
    expired = setup(client, "wanjiru@school.ke", code)
    assert expired.status_code == 400 and expired.json()["detail"] == wrong.json()["detail"]


def test_setup_is_throttled(client, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    for _ in range(5):
        setup(client, "wanjiru@school.ke", "AAAA-AAAA")
    # The right code is refused too while throttled - as with sign-in.
    assert setup(client, "wanjiru@school.ke", code).status_code == 429


def test_a_short_password_is_refused(client, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    assert setup(client, "wanjiru@school.ke", code, password="short").status_code == 422


def test_an_email_is_one_account_whatever_its_case(client, head):  # noqa: F811
    add(client, head)
    assert add(client, head, email="WANJIRU@school.ke").status_code == 409


def test_sign_in_ignores_the_case_of_the_email(client, head):  # noqa: F811
    assert login(client, "HEAD@School.ke", HEAD_PASSWORD).status_code == 200


def test_only_a_head_teacher_manages_staff(client, session):  # noqa: F811
    teacher = session.scalar(select(Teacher))
    assert client.get("/api/staff", headers=auth(teacher)).status_code == 403
    assert add(client, teacher).status_code == 403


def test_another_schools_teacher_is_not_found(client, session, head):  # noqa: F811
    rival = School(name="Rival", type="private")
    outsider = Teacher(name="R", email="r@x.y", password_hash="x", school=rival)
    session.add_all([rival, outsider])
    session.commit()
    r = client.post(f"/api/staff/{outsider.teacher_id}/deactivate", headers=auth(head))
    assert r.status_code == 404


# --- ending sessions -------------------------------------------------------
def test_a_new_code_ends_the_teachers_sessions_and_old_password(
    client, session, head  # noqa: F811
):
    code = add(client, head).json()["setup_code"]
    setup(client, "wanjiru@school.ke", code)
    t = session.scalar(select(Teacher).where(Teacher.email == "wanjiru@school.ke"))
    phone = held_token(session, t)
    assert me(client, phone).status_code == 200

    r = client.post(f"/api/staff/{t.teacher_id}/setup-code", headers=auth(head))
    assert r.status_code == 200 and r.json()["setup_code"] != code
    assert me(client, phone).status_code == 401
    assert login(client, "wanjiru@school.ke", "a-new-password").status_code == 401


def test_deactivation_takes_effect_at_once_and_is_reversible(client, session, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    setup(client, "wanjiru@school.ke", code)
    t = session.scalar(select(Teacher).where(Teacher.email == "wanjiru@school.ke"))

    assert client.post(f"/api/staff/{t.teacher_id}/deactivate",
                       headers=auth(head)).json()["status"] == "deactivated"
    assert me(client, auth(t)).status_code == 401  # even a token minted just now
    assert login(client, "wanjiru@school.ke", "a-new-password").status_code == 403

    client.post(f"/api/staff/{t.teacher_id}/reactivate", headers=auth(head))
    assert login(client, "wanjiru@school.ke", "a-new-password").status_code == 200


def test_a_deactivated_teachers_refresh_cookie_stops_working(client, session, head):  # noqa: F811
    code = add(client, head).json()["setup_code"]
    setup(client, "wanjiru@school.ke", code)  # sets the refresh cookie on this client
    t = session.scalar(select(Teacher).where(Teacher.email == "wanjiru@school.ke"))
    assert client.post("/api/auth/refresh").status_code == 200
    client.post(f"/api/staff/{t.teacher_id}/deactivate", headers=auth(head))
    assert client.post("/api/auth/refresh").status_code == 401


def test_changing_a_password_ends_other_sessions_but_not_this_one(
    client, session, head  # noqa: F811
):
    other_device = held_token(session, head)
    wrong = client.post("/api/auth/password", headers=auth(head),
                        json={"current_password": "nope", "new_password": "brand-new-pass"})
    assert wrong.status_code == 400

    r = client.post("/api/auth/password", headers=auth(head),
                    json={"current_password": HEAD_PASSWORD, "new_password": "brand-new-pass"})
    assert r.status_code == 200
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert me(client, fresh).status_code == 200
    assert me(client, other_device).status_code == 401
    assert login(client, "head@school.ke", "brand-new-pass").status_code == 200


def test_sign_out_everywhere_ends_every_session(client, session, head):  # noqa: F811
    login(client, "head@school.ke", HEAD_PASSWORD)  # a refresh cookie on this client
    phone = held_token(session, head)
    r = client.post("/api/auth/logout-everywhere", headers=phone)
    assert r.status_code == 200
    assert me(client, phone).status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401


# --- a school keeps its head -----------------------------------------------
def test_the_last_head_teacher_cannot_be_demoted_or_deactivated(
    client, session, head  # noqa: F811
):
    demote = client.patch(f"/api/staff/{head.teacher_id}", json={"role": "teacher"},
                          headers=auth(head))
    assert demote.status_code == 409

    second = add(client, head, email="deputy@school.ke", role="school_admin").json()
    assert client.patch(f"/api/staff/{head.teacher_id}", json={"role": "teacher"},
                        headers=auth(head)).status_code == 200
    assert second["role"] == "school_admin"


def test_a_head_teacher_cannot_lock_themselves_out(client, head):  # noqa: F811
    assert client.post(f"/api/staff/{head.teacher_id}/deactivate",
                       headers=auth(head)).status_code == 409
    assert client.post(f"/api/staff/{head.teacher_id}/setup-code",
                       headers=auth(head)).status_code == 409


def test_a_head_teacher_fixes_a_name_and_email(client, head):  # noqa: F811
    t = add(client, head).json()
    r = client.patch(f"/api/staff/{t['teacher_id']}", headers=auth(head),
                     json={"name": "Wanjiru Kamau", "email": "W.Kamau@school.ke"})
    assert r.json()["name"] == "Wanjiru Kamau" and r.json()["email"] == "w.kamau@school.ke"
