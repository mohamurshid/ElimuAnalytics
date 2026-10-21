"""
Quizzes of a set length.

The choice is pure and pinned here: spread across difficulty, the least
answered question in each band, the same answer every time for the same
data. The endpoint tests then hold the rules the choice serves: only
approved questions, never a key on the device, and a saved quiz that stays
the same when it is opened again.
"""

from __future__ import annotations

import uuid

import pytest
from app.db import get_session
from app.main import app
from app.models import Classroom, GenerationRun, Item, School, Strand, Teacher
from app.quizzes import Candidate, choose
from app.security import create_token
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def teacher(session) -> Teacher:  # noqa: F811
    return session.scalar(select(Teacher))


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def the_class(session) -> Classroom:  # noqa: F811
    return session.scalar(select(Classroom))


def make(client, session, **body):  # noqa: F811
    body = {"strand_id": str(session.strand_id), **body}
    return client.post(f"/api/classrooms/{the_class(session).class_id}/quizzes",
                       json=body, headers=auth(teacher(session)))


# --- the choice ------------------------------------------------------------
def c(item_id, difficulty=None, answers=0) -> Candidate:
    return Candidate(item_id, difficulty, answers)


def test_every_question_when_no_length_is_set_easy_to_hard():
    pool = [c("b", 1.0), c("a", -1.0), c("c", 0.5)]
    assert choose(pool, None) == ["a", "c", "b"]
    assert choose(pool, 5) == ["a", "c", "b"]


def test_the_quiz_spreads_across_difficulty():
    pool = [c(f"q{i}", difficulty=i - 5.0) for i in range(10)]  # -5 .. 4
    chosen = choose(pool, 2)
    assert chosen == ["q0", "q5"]  # one from the easier half, one from the harder


def test_within_a_band_the_least_answered_question_is_taken():
    pool = [c("easy-old", -2.0, answers=40), c("easy-new", -1.9, answers=3),
            c("hard-old", 2.0, answers=40), c("hard-new", 2.1, answers=0)]
    assert choose(pool, 2) == ["easy-new", "hard-new"]


def test_an_uncalibrated_question_sits_in_the_middle():
    pool = [c("hard", 2.0), c("new"), c("easy", -2.0)]
    assert choose(pool, None) == ["easy", "new", "hard"]


def test_the_same_data_gives_the_same_quiz():
    pool = [c(f"q{i}") for i in range(12)]
    assert choose(pool, 5) == choose(list(reversed(pool)), 5)


# --- making and reopening a quiz -------------------------------------------
def test_a_quiz_of_five_is_saved_and_reopens_unchanged(client, session):  # noqa: F811
    r = make(client, session, length=5)
    assert r.status_code == 201
    quiz = r.json()
    assert len(quiz["items"]) == 5 and quiz["mode"] == "device"
    again = client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth(teacher(session)))
    assert [i["item_id"] for i in again.json()["items"]] == [i["item_id"] for i in quiz["items"]]


def test_no_key_or_mark_scheme_is_in_a_quiz(client, session):  # noqa: F811
    r = make(client, session, length=10)
    for leak in ("correct_option", "misconception", "rationale"):
        assert leak not in r.text


def test_drafts_are_never_chosen(client, session):  # noqa: F811
    draft = Item(strand_id=session.strand_id, question_text="A draft nobody checked?",
                 options=["a", "b"], correct_option=0, status="draft", source="ai")
    session.add(draft)
    session.commit()
    ids = {i["item_id"] for i in make(client, session).json()["items"]}
    assert str(draft.item_id) not in ids
    assert len(ids) == 12


def test_a_paper_quiz_may_include_a_question_read_aloud(client, session):  # noqa: F811
    spoken = Item(strand_id=session.strand_id, question_text="Explain why pots have handles.",
                  status="approved")
    session.add(spoken)
    session.commit()
    device = {i["item_id"] for i in make(client, session).json()["items"]}
    paper = {i["item_id"] for i in make(client, session, mode="paper").json()["items"]}
    assert str(spoken.item_id) not in device
    assert str(spoken.item_id) in paper


def test_a_question_reported_after_printing_is_left_out_and_counted(
    client, session  # noqa: F811
):
    quiz = make(client, session, length=5).json()
    reported = session.get(Item, uuid.UUID(quiz["items"][0]["item_id"]))
    reported.status = "reported"
    session.commit()
    again = client.get(f"/api/quizzes/{quiz['quiz_id']}", headers=auth(teacher(session))).json()
    assert len(again["items"]) == 4 and again["withdrawn"] == 1
    # The rest keep their numbers, so the grid still matches the printed sheet.
    assert again["numbers"] == [2, 3, 4, 5]


def test_a_length_other_than_5_10_15_is_refused(client, session):  # noqa: F811
    assert make(client, session, length=7).status_code == 422


def test_a_strand_the_class_does_not_use_is_not_found(client, session):  # noqa: F811
    other = Strand(name="Elsewhere", level="Upper Primary")
    session.add(other)
    session.commit()
    assert make(client, session, strand_id=str(other.strand_id)).status_code == 404


def test_a_strand_with_no_approved_questions_is_refused(client, session):  # noqa: F811
    for item in session.scalars(select(Item)):
        item.status = "retired"
    session.commit()
    r = make(client, session)
    assert r.status_code == 409 and "no approved questions" in r.json()["detail"]


def test_another_schools_quiz_is_not_found(client, session):  # noqa: F811
    quiz = make(client, session).json()
    rival = School(name="Rival", type="private")
    outsider = Teacher(name="R", email="r@x.y", password_hash="x", school=rival)
    session.add_all([rival, outsider])
    session.commit()
    assert client.get(f"/api/quizzes/{quiz['quiz_id']}",
                      headers=auth(outsider)).status_code == 404


def test_recent_quizzes_are_listed_newest_first(client, session):  # noqa: F811
    make(client, session, length=5, mode="paper")
    make(client, session, length=10, mode="device")
    url = f"/api/classrooms/{the_class(session).class_id}/quizzes"
    every = client.get(url, headers=auth(teacher(session))).json()
    assert len(every) == 2
    paper = client.get(url, params={"mode": "paper"}, headers=auth(teacher(session))).json()
    assert [q["questions"] for q in paper] == [5]


# --- the strand page's generation status -----------------------------------
def test_the_strand_page_sees_what_is_left_today_and_what_is_running(
    client, session  # noqa: F811
):
    url = f"/api/strands/{session.strand_id}/generation"
    idle = client.get(url, headers=auth(teacher(session))).json()
    assert idle["remaining_today"] == 5 and idle["running"] is None

    session.add(GenerationRun(strand_id=session.strand_id,
                              school_id=teacher(session).school_id,
                              requested=5, status="pending"))
    session.commit()
    busy = client.get(url, headers=auth(teacher(session))).json()
    assert busy["running"]["status"] == "pending"
    assert busy["remaining_today"] == 4
