"""
Authentication, role enforcement and item bank tests.

The item tests are mostly about one thing: an item that learners have already
answered must never be destroyed or silently rewritten. Deleting it cascades to
its responses and changes every ability estimate derived from them; rewriting it
turns existing responses into answers to a question that no longer exists.
Neither failure would raise an error - both would just quietly move the numbers.
"""

from __future__ import annotations

import uuid

import pytest
from app.db import get_session
from app.items import router as items_router
from app.main import app
from app.models import Item, Teacher
from app.security import (
    ROLE_SCHOOL_ADMIN,
    ROLE_TEACHER,
    create_token,
    hash_password,
    role_at_least,
    verify_password,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

assert items_router  # imported for router registration side effects


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def teacher(session):  # noqa: F811
    t = session.scalar(select(Teacher))
    t.password_hash = hash_password("correct-horse")
    t.role = ROLE_TEACHER
    session.commit()
    return t


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


# --- password hashing ------------------------------------------------------
def test_passwords_are_hashed_not_stored():
    h = hash_password("correct-horse")
    assert h != "correct-horse"
    assert h.startswith("$2")  # bcrypt
    assert verify_password("correct-horse", h)
    assert not verify_password("wrong", h)


def test_placeholder_hash_fails_closed():
    """A seeded or malformed hash must reject every password, not raise."""
    assert verify_password("anything", "not-a-real-hash") is False


def test_role_ranking_is_ordered():
    assert role_at_least(ROLE_SCHOOL_ADMIN, ROLE_TEACHER)
    assert not role_at_least(ROLE_TEACHER, ROLE_SCHOOL_ADMIN)


# --- login -----------------------------------------------------------------
def test_login_returns_a_token(client, teacher):
    r = client.post("/api/auth/login",
                    json={"email": teacher.email, "password": "correct-horse"})
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["role"] == ROLE_TEACHER


def test_wrong_password_is_rejected(client, teacher):
    r = client.post("/api/auth/login",
                    json={"email": teacher.email, "password": "wrong"})
    assert r.status_code == 401


def test_unknown_and_wrong_password_are_indistinguishable(client, teacher):
    """Different messages would tell an attacker which addresses are registered."""
    a = client.post("/api/auth/login",
                    json={"email": teacher.email, "password": "wrong"})
    b = client.post("/api/auth/login",
                    json={"email": "nobody@example.school", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


# --- protected routes ------------------------------------------------------
def test_item_list_requires_authentication(client):
    assert client.get("/api/items").status_code == 401


def test_invalid_token_is_rejected(client):
    r = client.get("/api/items", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_authenticated_teacher_can_list_items(client, teacher):
    r = client.get("/api/items", headers=auth(teacher))
    assert r.status_code == 200
    assert len(r.json()) == 12


def test_me_returns_the_current_account(client, teacher):
    r = client.get("/api/auth/me", headers=auth(teacher))
    assert r.json()["email"] == teacher.email
    assert r.json()["role"] == ROLE_TEACHER


# --- item CRUD -------------------------------------------------------------
def test_teacher_can_create_an_item(client, teacher, session):  # noqa: F811
    r = client.post(
        "/api/items",
        headers=auth(teacher),
        json={"strand_id": str(session.strand_id),
              "question_text": "Why does a metal roof feel hot at midday?"},
    )
    assert r.status_code == 201
    assert r.json()["is_active"] is True
    assert r.json()["response_count"] == 0


def test_unanswered_item_can_be_edited(client, teacher, session):  # noqa: F811
    created = client.post(
        "/api/items", headers=auth(teacher),
        json={"strand_id": str(session.strand_id), "question_text": "Draft question?"},
    ).json()
    r = client.patch(f"/api/items/{created['item_id']}", headers=auth(teacher),
                     json={"question_text": "Revised question about heat?"})
    assert r.status_code == 200
    assert r.json()["question_text"] == "Revised question about heat?"


def test_answered_item_cannot_be_rewritten(client, teacher, session):  # noqa: F811
    """Existing responses would become answers to a question that no longer exists."""
    item = session.scalars(select(Item)).first()
    r = client.patch(f"/api/items/{item.item_id}", headers=auth(teacher),
                     json={"question_text": "A completely different question?"})
    assert r.status_code == 409
    assert "already recorded" in r.json()["detail"]


def test_teacher_cannot_delete(client, teacher, session):  # noqa: F811
    item = session.scalars(select(Item)).first()
    r = client.delete(f"/api/items/{item.item_id}", headers=auth(teacher))
    assert r.status_code == 403
    assert "school_admin" in r.json()["detail"]


def test_school_admin_deleting_an_answered_item_deactivates_it(
    client, teacher, session  # noqa: F811
):
    """The safeguard: responses are preserved, the item leaves the active bank."""
    teacher.role = ROLE_SCHOOL_ADMIN
    session.commit()
    item = session.scalars(select(Item)).first()

    r = client.delete(f"/api/items/{item.item_id}", headers=auth(teacher))
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is False
    assert body["deactivated"] is True
    assert body["response_count"] > 0

    session.refresh(item)
    assert item.is_active is False
    assert session.get(Item, item.item_id) is not None


def test_unanswered_item_is_deleted_outright(client, teacher, session):  # noqa: F811
    teacher.role = ROLE_SCHOOL_ADMIN
    session.commit()
    created = client.post(
        "/api/items", headers=auth(teacher),
        json={"strand_id": str(session.strand_id), "question_text": "Throwaway item?"},
    ).json()

    r = client.delete(f"/api/items/{created['item_id']}", headers=auth(teacher))
    assert r.json()["deleted"] is True
    assert session.get(Item, uuid.UUID(created["item_id"])) is None


def test_deactivated_items_leave_the_calibration_pool(client, teacher, session):  # noqa: F811
    """Withdrawing an item must change what future calibrations see."""
    from app.repository import build_response_matrix

    before, _, _ = build_response_matrix(session, session.strand_id)
    teacher.role = ROLE_SCHOOL_ADMIN
    session.commit()
    item = session.scalars(select(Item)).first()
    client.delete(f"/api/items/{item.item_id}", headers=auth(teacher))

    after, _, _ = build_response_matrix(session, session.strand_id)
    assert after.shape[0] == before.shape[0] - 1


def test_assessment_still_requires_a_token(client):
    r = client.post(f"/api/strands/{uuid.uuid4()}/assess")
    assert r.status_code == 401
