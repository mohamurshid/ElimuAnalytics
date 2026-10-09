"""
Classroom and learner record tests.

Two things are being guarded here, and only one of them is ordinary CRUD.

The first is **isolation**. These endpoints are where children's records cross
a trust boundary for the first time, so a teacher at one school must not be
able to read, rename, move or withdraw a learner at another - and must not be
able to tell, from the response, whether that learner exists at all.

The second is the **deletion safeguard**, which is the item-bank rule applied
to people. A learner who has answered anything can never be destroyed: the
cascade would take their responses, and recalibrating a strand without those
responses moves the ability estimate of every other learner who sat the same
items. That failure raises no error - it just quietly changes the numbers.
"""

from __future__ import annotations

import pytest
from app.db import get_session
from app.main import app
from app.models import Classroom, School, Student, Teacher
from app.security import ROLE_SCHOOL_ADMIN, ROLE_TEACHER, create_token, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

PASSWORD = "correct-horse"


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def head(session):  # noqa: F811
    """The seeded teacher, promoted to school_admin."""
    t = session.scalar(select(Teacher))
    t.password_hash = hash_password(PASSWORD)
    t.role = ROLE_SCHOOL_ADMIN
    session.commit()
    return t


@pytest.fixture
def rival(session):  # noqa: F811
    """A school_admin at a completely different school, with one learner."""
    school = School(name="Rival School", type="private")
    teacher = Teacher(
        name="Rival Head",
        email="head@rival.school",
        password_hash=hash_password(PASSWORD),
        role=ROLE_SCHOOL_ADMIN,
        school=school,
    )
    classroom = Classroom(grade="Grade 4", name="Red", school=school, teacher=teacher)
    student = Student(name="Rival Learner", classroom=classroom)
    session.add_all([school, teacher, classroom, student])
    session.commit()
    session.refresh(teacher)
    session.refresh(classroom)
    session.refresh(student)
    return {"teacher": teacher, "classroom": classroom, "student": student}


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def only_classroom(client, t) -> dict:
    rows = client.get("/api/classrooms", headers=auth(t)).json()
    assert rows, "expected at least one classroom"
    return rows[0]


# --- isolation -------------------------------------------------------------
def test_listing_shows_only_your_own_school(client, head, rival):
    rows = client.get("/api/classrooms", headers=auth(head)).json()
    assert [r["grade"] for r in rows] == ["Grade 5"]
    assert str(rival["classroom"].class_id) not in [r["class_id"] for r in rows]


def test_another_schools_classroom_is_not_found(client, head, rival):
    """404, not 403. A 403 would confirm the record exists."""
    r = client.get(
        f"/api/classrooms/{rival['classroom'].class_id}/students", headers=auth(head)
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "No such classroom"


def test_another_schools_learner_is_not_found(client, head, rival):
    r = client.get(f"/api/students/{rival['student'].student_id}", headers=auth(head))
    assert r.status_code == 404


def test_a_missing_record_and_a_forbidden_one_are_indistinguishable(client, head, rival):
    """The whole point of answering 404: an attacker walking identifiers
    cannot tell a real learner at another school from one that never existed."""
    import uuid as _uuid

    real_elsewhere = client.get(
        f"/api/students/{rival['student'].student_id}", headers=auth(head)
    )
    never_existed = client.get(f"/api/students/{_uuid.uuid4()}", headers=auth(head))
    assert real_elsewhere.status_code == never_existed.status_code == 404
    assert real_elsewhere.json() == never_existed.json()


def test_cannot_withdraw_another_schools_learner(client, head, rival):
    r = client.delete(
        f"/api/students/{rival['student'].student_id}", headers=auth(head)
    )
    assert r.status_code == 404
    assert client.get(
        f"/api/students/{rival['student'].student_id}", headers=auth(rival["teacher"])
    ).status_code == 200


def test_cannot_transfer_a_learner_into_another_school(client, head, rival, session):  # noqa: F811
    """A transfer is scoped at the destination too, or it becomes a way to
    move a child's whole record out of the school that holds it."""
    learner = session.scalar(select(Student))
    r = client.patch(
        f"/api/students/{learner.student_id}",
        headers=auth(head),
        json={"class_id": str(rival["classroom"].class_id)},
    )
    assert r.status_code == 404


def test_a_new_classroom_lands_in_your_own_school(client, head, rival, session):  # noqa: F811
    """school_id comes from the token, never the request body."""
    created = client.post(
        "/api/classrooms", headers=auth(head), json={"grade": "Grade 6", "name": "Green"}
    ).json()
    classroom = session.get(Classroom, __import__("uuid").UUID(created["class_id"]))
    assert classroom.school_id == head.school_id
    assert classroom.school_id != rival["teacher"].school_id


def test_endpoints_require_authentication(client):
    assert client.get("/api/classrooms").status_code == 401


# --- CRUD ------------------------------------------------------------------
def test_create_list_and_rename_a_classroom(client, head):
    created = client.post(
        "/api/classrooms", headers=auth(head), json={"grade": "Grade 6", "name": "Green"}
    )
    assert created.status_code == 201
    assert created.json()["student_count"] == 0

    cid = created.json()["class_id"]
    renamed = client.patch(
        f"/api/classrooms/{cid}", headers=auth(head), json={"name": "Yellow"}
    )
    assert renamed.json()["name"] == "Yellow"


def test_a_teacher_cannot_create_a_classroom(client, session, head):  # noqa: F811
    head.role = ROLE_TEACHER
    session.commit()
    r = client.post("/api/classrooms", headers=auth(head), json={"grade": "Grade 6"})
    assert r.status_code == 403


def test_enrol_a_learner_and_see_them_on_the_roll(client, head):
    cid = client.post(
        "/api/classrooms", headers=auth(head), json={"grade": "Grade 6", "name": "Green"}
    ).json()["class_id"]

    enrolled = client.post(
        f"/api/classrooms/{cid}/students", headers=auth(head), json={"name": "Wanjiru A."}
    )
    assert enrolled.status_code == 201
    assert enrolled.json()["response_count"] == 0

    roll = client.get(f"/api/classrooms/{cid}/students", headers=auth(head)).json()
    assert [s["name"] for s in roll] == ["Wanjiru A."]


def test_cannot_enrol_into_a_withdrawn_classroom(client, head):
    cid = client.post(
        "/api/classrooms", headers=auth(head), json={"grade": "Grade 6"}
    ).json()["class_id"]
    client.patch(f"/api/classrooms/{cid}", headers=auth(head), json={"is_active": False})

    r = client.post(
        f"/api/classrooms/{cid}/students", headers=auth(head), json={"name": "Too Late"}
    )
    assert r.status_code == 409


# --- the deletion safeguard ------------------------------------------------
def test_a_learner_who_answered_nothing_is_deleted_outright(client, head, session):  # noqa: F811
    cid = only_classroom(client, head)["class_id"]
    sid = client.post(
        f"/api/classrooms/{cid}/students", headers=auth(head), json={"name": "Never Sat"}
    ).json()["student_id"]

    r = client.delete(f"/api/students/{sid}", headers=auth(head))
    assert r.json()["deleted"] is True
    assert session.get(Student, __import__("uuid").UUID(sid)) is None


def test_a_learner_who_answered_is_withdrawn_not_deleted(client, head, session):  # noqa: F811
    """The safeguard. Their responses are other learners' evidence too."""
    learner = session.scalar(select(Student).order_by(Student.name))

    r = client.delete(f"/api/students/{learner.student_id}", headers=auth(head))
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is False
    assert body["deactivated"] is True
    assert body["response_count"] > 0

    session.refresh(learner)
    assert learner.is_active is False
    assert session.get(Student, learner.student_id) is not None


def test_a_withdrawn_learner_leaves_the_calibration_pool(client, head, session):  # noqa: F811
    """Withdrawing must actually change what the next calibration sees, or it
    is only a flag on a row."""
    from app.repository import build_response_matrix

    before, _, _ = build_response_matrix(session, session.strand_id)
    learner = session.scalar(select(Student).order_by(Student.name))
    client.delete(f"/api/students/{learner.student_id}", headers=auth(head))

    after, _, _ = build_response_matrix(session, session.strand_id)
    assert after.shape[1] == before.shape[1] - 1
    assert after.shape[0] == before.shape[0]  # items unaffected


def test_a_classroom_with_answers_is_withdrawn_with_its_learners(client, head, session):  # noqa: F811
    cid = only_classroom(client, head)["class_id"]

    r = client.delete(f"/api/classrooms/{cid}", headers=auth(head))
    body = r.json()
    assert body["deleted"] is False and body["deactivated"] is True
    assert body["response_count"] > 0

    remaining = session.scalars(select(Student).where(Student.is_active.is_(True))).all()
    assert remaining == []


def test_an_empty_classroom_is_deleted_outright(client, head, session):  # noqa: F811
    cid = client.post(
        "/api/classrooms", headers=auth(head), json={"grade": "Grade 6", "name": "Green"}
    ).json()["class_id"]

    r = client.delete(f"/api/classrooms/{cid}", headers=auth(head))
    assert r.json()["deleted"] is True
    assert session.get(Classroom, __import__("uuid").UUID(cid)) is None


def test_a_teacher_cannot_withdraw_a_learner(client, session, head):  # noqa: F811
    """Withdrawing changes what future calibrations are computed from, so it
    is a school-administrator action - the same reasoning as the item bank."""
    learner = session.scalar(select(Student))
    head.role = ROLE_TEACHER
    session.commit()

    r = client.delete(f"/api/students/{learner.student_id}", headers=auth(head))
    assert r.status_code == 403
