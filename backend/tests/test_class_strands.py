"""
What a class is assessed on.

Three properties matter more than the plumbing:

**Removing a strand loses nothing.** It unlinks; the answers stay, and
adding the strand back brings the learners' levels back. A test counts the
responses either side rather than trusting the docstring.

**Strands are shared, not copied.** Two schools picking the same sub-strand
must get the same row, or the question bank and its calibration split in
two.

**Only the class's strands reach the class's screens.** The heatmap used to
show every strand in the database, which was harmless with one.
"""

from __future__ import annotations

import pytest
from app.catalogue import catalogue_rows
from app.db import get_session
from app.main import app
from app.models import Classroom, Response, School, Strand, Student, Teacher
from app.security import create_token
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .test_catalogue import corpus_rows  # noqa: F401 - pytest fixture
from .test_repository import session  # noqa: F401 - pytest fixture

HEAT = "Grade 5|Science and Technology|3.0|3.3"
SOUND = "Grade 5|Science and Technology|3.0|3.2"
GRADE_4_HEAT = "Grade 4|Science and Technology|3.0|3.3"


@pytest.fixture
def client(session, corpus_rows):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[catalogue_rows] = lambda: corpus_rows
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def teacher(session) -> Teacher:  # noqa: F811
    """The fixture's account, which is an ordinary teacher, not a head."""
    t = session.scalar(select(Teacher))
    assert t.role == "teacher"
    return t


def the_class(session) -> Classroom:  # noqa: F811
    return session.scalar(select(Classroom))


def strands_url(classroom: Classroom) -> str:
    return f"/api/classrooms/{classroom.class_id}/strands"


def add(client, session, key: str, classroom: Classroom | None = None, who=None):  # noqa: F811
    classroom = classroom or the_class(session)
    return client.post(strands_url(classroom), json={"key": key},
                       headers=auth(who or teacher(session)))


def heatmap(client, session):  # noqa: F811
    r = client.get(f"/api/classrooms/{the_class(session).class_id}/heatmap",
                   headers=auth(teacher(session)))
    assert r.status_code == 200
    return r.json()


# --- listing ---------------------------------------------------------------
def test_a_class_lists_the_strands_it_is_assessed_on(client, session):  # noqa: F811
    r = client.get(strands_url(the_class(session)), headers=auth(teacher(session)))
    assert r.status_code == 200
    assert [s["name"] for s in r.json()] == ["3.3 Heat Transfer"]


def test_strand_endpoints_need_a_signed_in_teacher(client, session):  # noqa: F811
    url = strands_url(the_class(session))
    assert client.get(url).status_code == 401
    assert client.post(url, json={"key": SOUND}).status_code == 401


# --- adding ----------------------------------------------------------------
def test_any_teacher_adds_a_sub_strand_from_the_catalogue(client, session):  # noqa: F811
    r = add(client, session, SOUND)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Force and Energy / 3.2 Sound Energy"
    assert body["grade"] == "Grade 5"
    assert body["learning_area"] == "Science and Technology"
    assert body["curriculum_key"] == SOUND
    assert body["active_items"] == 0  # no questions until generation fills it

    listed = client.get(strands_url(the_class(session)), headers=auth(teacher(session)))
    assert len(listed.json()) == 2
    assert len(heatmap(client, session)["strands"]) == 2


def test_adding_twice_is_not_an_error_and_makes_one_link(client, session):  # noqa: F811
    first = add(client, session, SOUND)
    second = add(client, session, SOUND)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["strand_id"] == second.json()["strand_id"]
    assert session.scalar(
        select(func.count()).select_from(Strand).where(Strand.curriculum_key == SOUND)
    ) == 1
    assert len(heatmap(client, session)["strands"]) == 2


def test_a_strand_is_shared_across_schools_not_copied(client, session):  # noqa: F811
    other_school = School(name="Other", type="public")
    other_teacher = Teacher(name="O", email="o@x.y", password_hash="x", school=other_school)
    other_class = Classroom(grade="Grade 5", name="Red", school=other_school,
                            teacher=other_teacher)
    session.add_all([other_school, other_teacher, other_class])
    session.commit()

    ours = add(client, session, SOUND)
    theirs = add(client, session, SOUND, classroom=other_class, who=other_teacher)
    assert theirs.status_code == 201
    assert ours.json()["strand_id"] == theirs.json()["strand_id"]


def test_a_lower_grades_sub_strand_can_be_picked(client, session):  # noqa: F811
    """Remediation: a Grade 5 class revisiting Grade 4 heat."""
    r = add(client, session, GRADE_4_HEAT)
    assert r.status_code == 201
    assert r.json()["grade"] == "Grade 4"


def test_a_key_not_in_the_catalogue_is_refused(client, session):  # noqa: F811
    assert add(client, session, "Grade 5|Science and Technology|3.0|9.9").status_code == 422
    # Outside the catalogue's scope, though a real sub-strand.
    assert add(client, session, "Grade 2|Kiswahili|1.0|1.1").status_code == 422


def test_another_schools_class_is_not_found(client, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 5", name="Red", school=rival_school)
    session.add_all([rival_school, rival_class])
    session.commit()
    url = strands_url(rival_class)
    me = auth(teacher(session))
    assert client.get(url, headers=me).status_code == 404
    assert client.post(url, json={"key": SOUND}, headers=me).status_code == 404


def test_a_withdrawn_class_cannot_change_what_it_is_assessed_on(client, session):  # noqa: F811
    classroom = the_class(session)
    heat = session.scalar(select(Strand))
    classroom.is_active = False
    session.commit()
    assert add(client, session, SOUND).status_code == 409
    r = client.delete(f"{strands_url(classroom)}/{heat.strand_id}",
                      headers=auth(teacher(session)))
    assert r.status_code == 409


def test_strands_are_listed_in_curriculum_order_not_by_name(client, session):  # noqa: F811
    """The seeded name starts "3.0 Force and Energy /" and catalogue names do
    not, so sorting by name put 3.3 before 3.2."""
    heat = session.scalar(select(Strand))
    heat.grade, heat.learning_area, heat.curriculum_key = (
        "Grade 5", "Science and Technology", HEAT,
    )
    session.commit()
    add(client, session, SOUND)
    add(client, session, GRADE_4_HEAT)

    r = client.get(strands_url(the_class(session)), headers=auth(teacher(session)))
    assert [s["curriculum_key"] for s in r.json()] == [GRADE_4_HEAT, SOUND, HEAT]
    assert [s["curriculum_key"] for s in heatmap(client, session)["strands"]] == [
        GRADE_4_HEAT, SOUND, HEAT,
    ]


# --- removing --------------------------------------------------------------
def test_removing_a_strand_keeps_every_answer_and_adding_it_back_restores_levels(
    client, session  # noqa: F811
):
    heat = session.scalar(select(Strand))
    heat.curriculum_key = HEAT  # as the seed sets it
    session.commit()
    answers = session.scalar(select(func.count()).select_from(Response))
    before = heatmap(client, session)

    r = client.delete(f"{strands_url(the_class(session))}/{heat.strand_id}",
                      headers=auth(teacher(session)))
    assert r.status_code == 200
    assert r.json() == {"removed": True}
    assert session.scalar(select(func.count()).select_from(Response)) == answers
    assert heatmap(client, session)["strands"] == []

    # Picked again from the catalogue: the same row, so the same answers.
    again = add(client, session, HEAT)
    assert again.status_code == 201
    assert again.json()["strand_id"] == str(heat.strand_id)
    assert heatmap(client, session)["learners"] == before["learners"]


def test_removing_a_strand_the_class_does_not_have_is_not_found(client, session):  # noqa: F811
    other = Strand(name="3.2 Sound Energy", level="Upper Primary")
    session.add(other)
    session.commit()
    r = client.delete(f"{strands_url(the_class(session))}/{other.strand_id}",
                      headers=auth(teacher(session)))
    assert r.status_code == 404


# --- what other screens see ------------------------------------------------
def test_a_strand_no_class_uses_is_not_listed_for_the_school(client, session):  # noqa: F811
    session.add(Strand(name="Unused", level="Upper Primary"))
    session.commit()
    r = client.get("/api/strands", headers=auth(teacher(session)))
    assert [s["name"] for s in r.json()] == ["3.3 Heat Transfer"]


def test_a_learner_is_diagnosed_only_on_their_class_strands(client, session):  # noqa: F811
    session.add(Strand(name="Unused", level="Upper Primary"))
    session.commit()
    learner = session.scalar(select(Student).where(Student.name.like("Chebet%")))
    r = client.get(f"/api/students/{learner.student_id}/diagnostics",
                   headers=auth(teacher(session)))
    assert [c["strand"] for c in r.json()["cells"]] == ["3.3 Heat Transfer"]
