"""
Diagnostics read-endpoint tests.

Two things worth guarding beyond "it returns JSON".

**The heatmap must not calibrate per learner.** Calibration is a property of
the strand. The Phase 2 version of this mistake took the test suite from 5.9
seconds to 97; on a read path hit every time a teacher opens the dashboard it
would be worse. The test below asserts the call count directly rather than
timing it, because a timing test is flaky on shared hardware.

**"No estimate" must be a reported state, not an absent one.** A learner below
the evidence threshold has to come back as `insufficient_evidence` with a
message, so the interface can render a deliberate refusal rather than a blank
cell that reads as a rendering fault.
"""

from __future__ import annotations

import uuid

import pytest
from app.db import get_session
from app.main import app
from app.models import Classroom, School, Student, Teacher
from app.security import ROLE_SCHOOL_ADMIN, create_token, hash_password
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
    t = session.scalar(select(Teacher))
    t.password_hash = hash_password(PASSWORD)
    t.role = ROLE_SCHOOL_ADMIN
    session.commit()
    return t


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def the_class(session) -> Classroom:  # noqa: F811
    return session.scalar(select(Classroom))


# --- strands ---------------------------------------------------------------
def test_strands_are_listed_with_item_counts(client, head):
    r = client.get("/api/strands", headers=auth(head))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "3.3 Heat Transfer"
    assert rows[0]["active_items"] == 12
    assert rows[0]["calibrated_items"] == 0  # nothing calibrated yet


def test_strands_require_authentication(client):
    assert client.get("/api/strands").status_code == 401


# --- learner diagnostics ---------------------------------------------------
def test_a_learner_is_diagnosed_per_strand(client, head, session):  # noqa: F811
    chebet = session.scalar(select(Student).where(Student.name.like("Chebet%")))
    r = client.get(f"/api/students/{chebet.student_id}/diagnostics", headers=auth(head))

    assert r.status_code == 200
    body = r.json()
    assert body["name"] == chebet.name
    assert len(body["cells"]) == 1
    cell = body["cells"][0]
    assert cell["answered"] == 12
    assert cell["status"] == "estimated"
    assert cell["theta"] == pytest.approx(-1.74, abs=0.05)
    assert cell["tier"] == "Below expectation"


def test_insufficient_evidence_is_a_reported_state(client, head, session):  # noqa: F811
    """Otieno answered three items. The interface must be told that, not
    handed a null it has to guess the meaning of."""
    otieno = session.scalar(select(Student).where(Student.name.like("Otieno%")))
    r = client.get(f"/api/students/{otieno.student_id}/diagnostics", headers=auth(head))

    cell = r.json()["cells"][0]
    assert cell["status"] == "insufficient_evidence"
    assert cell["theta"] is None
    assert cell["tier"] is None
    assert cell["answered"] == 3
    assert "5" in cell["message"]  # states the threshold


def test_a_named_strand_can_be_requested(client, head, session):  # noqa: F811
    """The Phase 1 endpoint used whichever strand sorted first."""
    chebet = session.scalar(select(Student).where(Student.name.like("Chebet%")))
    strand_id = client.get("/api/strands", headers=auth(head)).json()[0]["strand_id"]

    r = client.get(
        f"/api/students/{chebet.student_id}/diagnostics?strand_id={strand_id}",
        headers=auth(head),
    )
    assert r.status_code == 200
    assert len(r.json()["cells"]) == 1

    missing = client.get(
        f"/api/students/{chebet.student_id}/diagnostics?strand_id={uuid.uuid4()}",
        headers=auth(head),
    )
    assert missing.status_code == 404


def test_another_schools_learner_is_not_diagnosable(client, head, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    outsider = Student(name="Outsider", classroom=rival_class)
    session.add_all([rival_school, rival_class, outsider])
    session.commit()
    session.refresh(outsider)

    r = client.get(f"/api/students/{outsider.student_id}/diagnostics", headers=auth(head))
    assert r.status_code == 404


# --- heatmap ---------------------------------------------------------------
def test_the_heatmap_returns_every_learner_against_every_strand(client, head, session):  # noqa: F811
    classroom = the_class(session)
    r = client.get(f"/api/classrooms/{classroom.class_id}/heatmap", headers=auth(head))

    assert r.status_code == 200
    body = r.json()
    assert body["grade"] == "Grade 5"
    assert len(body["strands"]) == 1
    assert len(body["learners"]) == 40
    assert all(len(lr["cells"]) == 1 for lr in body["learners"])
    assert body["minimum_responses"] == 5
    assert body["confident_responses"] == 10


def test_the_heatmap_calibrates_once_per_strand_not_once_per_learner(
    client, head, session, monkeypatch  # noqa: F811
):
    """Forty learners, one strand, one calibration. The Phase 2 bug was this
    shape and cost the test suite 91 seconds."""
    from app import irt

    calls = {"n": 0}
    real = irt.calibrate

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(irt, "calibrate", counted)

    classroom = the_class(session)
    r = client.get(f"/api/classrooms/{classroom.class_id}/heatmap", headers=auth(head))
    assert r.status_code == 200
    assert calls["n"] == 1


def test_a_withdrawn_learner_is_absent_from_the_heatmap(client, head, session):  # noqa: F811
    classroom = the_class(session)
    learner = session.scalar(select(Student).order_by(Student.name))
    learner.is_active = False
    session.commit()

    body = client.get(
        f"/api/classrooms/{classroom.class_id}/heatmap", headers=auth(head)
    ).json()
    assert learner.name not in [lr["name"] for lr in body["learners"]]


def test_another_schools_heatmap_is_not_found(client, head, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    session.add_all([rival_school, rival_class])
    session.commit()
    session.refresh(rival_class)

    r = client.get(f"/api/classrooms/{rival_class.class_id}/heatmap", headers=auth(head))
    assert r.status_code == 404


# --- the intervention queue ------------------------------------------------
def test_the_queue_requires_authentication(client):
    assert client.get("/api/flags").status_code == 401


def test_the_queue_is_empty_before_two_assessments(client, head, session):  # noqa: F811
    strand_id = client.get("/api/strands", headers=auth(head)).json()[0]["strand_id"]
    client.post(f"/api/strands/{strand_id}/assess", headers=auth(head))

    assert client.get("/api/flags", headers=auth(head)).json() == []


def test_the_queue_names_the_learner_and_strand_after_two(client, head, session):  # noqa: F811
    strand_id = client.get("/api/strands", headers=auth(head)).json()[0]["strand_id"]
    client.post(f"/api/strands/{strand_id}/assess", headers=auth(head))
    client.post(f"/api/strands/{strand_id}/assess", headers=auth(head))

    rows = client.get("/api/flags", headers=auth(head)).json()
    assert rows, "two consecutive below-threshold assessments should raise a flag"
    assert all(r["learner"] and r["strand"] for r in rows)
    assert "Chebet" in " ".join(r["learner"] for r in rows)
    # Otieno never had a valid estimate, so he can never appear.
    assert "Otieno" not in " ".join(r["learner"] for r in rows)


def test_the_queue_hides_other_schools(client, head, session):  # noqa: F811
    """Previously this endpoint returned every open flag in the database."""
    from app.models import GapFlag, Strand

    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    outsider = Student(name="Outsider", classroom=rival_class)
    strand = session.scalar(select(Strand))
    session.add_all([rival_school, rival_class, outsider])
    session.flush()
    session.add(
        GapFlag(
            student_id=outsider.student_id,
            strand_id=strand.strand_id,
            severity="Below expectation",
        )
    )
    session.commit()

    rows = client.get("/api/flags", headers=auth(head)).json()
    assert "Outsider" not in " ".join(r["learner"] for r in rows)
