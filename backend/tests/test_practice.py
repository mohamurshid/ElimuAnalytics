"""
Practice sets chosen from a learner's own level.

The choice is pure and pinned here: the questions nearest a 0.7 chance for
this learner, only questions that can be placed, the same set for the same
data, easy to hard. The endpoint tests then hold the rules around it: only
questions the learner has not answered, never a key, nothing without an
estimate, and nothing from another school.
"""

from __future__ import annotations

import uuid

import pytest
from app.models import Item, QuizSet, Response, School, Strand, Teacher
from app.practice import TARGET, Calibrated, chance, choose_practice
from sqlalchemy import select

from .test_quizzes import auth, client, teacher  # noqa: F401 - fixtures and helpers
from .test_repository import session  # noqa: F401 - pytest fixture


# --- the choice ------------------------------------------------------------
def q(item_id, b=None, a=1.0) -> Calibrated:
    return Calibrated(item_id, b, a)


def test_chance_is_the_2pl_curve():
    assert chance(0.0, 0.0, 1.0) == pytest.approx(0.5)
    assert chance(1.0, 0.0, 1.0) > 0.7 > chance(0.0, 0.0, 1.0)
    # A sharper question separates more steeply either side of its difficulty.
    assert chance(0.5, 0.0, 2.0) > chance(0.5, 0.0, 1.0)


def test_questions_nearest_the_target_chance_are_chosen():
    # For theta 0 and a = 1, P = 0.7 at b = -ln(0.7/0.3), about -0.85.
    pool = [q(f"b{b}", b=b / 10) for b in range(-30, 31, 5)]  # -3.0 .. 3.0
    chosen = choose_practice(0.0, pool, length=3)
    assert [i for i, _ in chosen] == ["b-15", "b-10", "b-5"]
    assert all(abs(p - TARGET) < 0.15 for _, p in chosen)


def test_the_set_moves_with_the_learner():
    pool = [q(f"b{b}", b=float(b)) for b in range(-3, 4)]
    weaker = [i for i, _ in choose_practice(-1.5, pool, length=2)]
    stronger = [i for i, _ in choose_practice(1.5, pool, length=2)]
    assert weaker == ["b-3", "b-2"] and stronger == ["b0", "b1"]


def test_a_question_already_secure_is_left_out():
    pool = [q("certain", b=-6.0), q("near", b=-0.85)]
    assert [i for i, _ in choose_practice(0.0, pool, length=5)] == ["near"]


def test_uncalibrated_or_inverted_questions_are_not_placed():
    pool = [q("new", b=None), q("odd", b=-1.0, a=-0.4), q("flat", b=-1.0, a=0.0), q("ok", b=-1.0)]
    assert [i for i, _ in choose_practice(0.0, pool, length=5)] == ["ok"]


def test_most_likely_first_and_the_same_every_time():
    pool = [q(f"x{i}", b=-0.85) for i in range(8)]
    first = choose_practice(0.0, pool, length=4)
    assert first == choose_practice(0.0, list(reversed(pool)), length=4)
    spread = [q("hard", b=-0.5), q("easy", b=-1.2), q("mid", b=-0.85)]
    assert [i for i, _ in choose_practice(0.0, spread, length=3)] == ["easy", "mid", "hard"]
    # By this learner's chance, not by difficulty: a sharp question just above
    # a weak learner is less likely for them than a flat one slightly harder.
    mixed = [q("sharp", b=-1.0, a=3.0), q("flat", b=-0.8, a=0.4)]
    order = choose_practice(-2.0, mixed, length=2)
    assert [i for i, _ in order] == ["flat", "sharp"]
    assert order[0][1] > order[1][1]


# --- the endpoint ----------------------------------------------------------
def calibrate_bank(session) -> None:  # noqa: F811
    """Store parameters on the seeded bank, as Recalibrate would."""
    for n, item in enumerate(session.scalars(select(Item).order_by(Item.item_id))):
        item.difficulty_b = -1.5 + n * 0.25
        item.discrimination_a = 1.2
    session.commit()


def add_fresh(session, count=6, start=-2.0):  # noqa: F811
    """Approved, calibrated questions nobody has answered yet."""
    fresh = [
        Item(strand_id=session.strand_id, question_text=f"Fresh question {n}?",
             options=["a", "b", "c", "d"], correct_option=0, status="approved",
             difficulty_b=start + n * 0.5, discrimination_a=1.0)
        for n in range(count)
    ]
    session.add_all(fresh)
    session.commit()
    return fresh


def practise(client, session, student, **body):  # noqa: F811
    body = {"strand_id": str(session.strand_id), **body}
    return client.post(f"/api/students/{student.student_id}/practice",
                       json=body, headers=auth(teacher(session)))


def test_a_practice_set_is_chosen_from_questions_the_learner_has_not_answered(
    client, session  # noqa: F811
):
    calibrate_bank(session)
    fresh = add_fresh(session)
    learner = session.students[0]
    r = practise(client, session, learner)
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["items"]) == 5
    assert {i["item_id"] for i in body["items"]} <= {str(i.item_id) for i in fresh}
    assert body["target"] == TARGET and body["theta"] is not None
    # Each chance is the model's, for this learner.
    for item in body["items"]:
        stored = session.get(Item, uuid.UUID(item["item_id"]))
        assert item["chance"] == pytest.approx(
            chance(body["theta"], stored.difficulty_b, stored.discrimination_a), abs=0.01)


def test_the_set_is_saved_and_reopens_as_a_quiz_without_the_key(client, session):  # noqa: F811
    calibrate_bank(session)
    add_fresh(session)
    body = practise(client, session, session.students[1]).json()
    saved = session.get(QuizSet, uuid.UUID(body["quiz_id"]))
    assert saved.mode == "practice"
    again = client.get(f"/api/quizzes/{body['quiz_id']}", headers=auth(teacher(session)))
    assert [i["item_id"] for i in again.json()["items"]] == [i["item_id"] for i in body["items"]]
    for leak in ("correct_option", "misconception", "rationale"):
        assert leak not in again.text and leak not in str(body)


def test_answering_the_set_changes_what_comes_next(client, session):  # noqa: F811
    calibrate_bank(session)
    add_fresh(session, count=10)
    learner = session.students[6]
    first = practise(client, session, learner).json()
    for item in first["items"]:
        session.add(Response(student_id=learner.student_id,
                             item_id=uuid.UUID(item["item_id"]), correctness=True))
    session.commit()
    second = practise(client, session, learner).json()
    assert not {i["item_id"] for i in first["items"]} & {i["item_id"] for i in second["items"]}
    assert second["theta"] > first["theta"]


def test_no_estimate_no_practice_set(client, session):  # noqa: F811
    calibrate_bank(session)
    add_fresh(session)
    # Otieno answered only three questions: no level, so nothing to choose from.
    r = practise(client, session, session.students[2])
    assert r.status_code == 409 and "at least five" in r.json()["detail"]


def test_only_uncalibrated_questions_left_says_so(client, session):  # noqa: F811
    calibrate_bank(session)
    session.add(Item(strand_id=session.strand_id, question_text="Brand new?",
                     options=["a", "b"], correct_option=1, status="approved"))
    session.commit()
    r = practise(client, session, session.students[4])
    assert r.status_code == 409 and "calibrated" in r.json()["detail"]


def test_only_secure_questions_left_says_so(client, session):  # noqa: F811
    calibrate_bank(session)
    add_fresh(session, count=3, start=-9.0)  # far below anyone: certain to be right
    r = practise(client, session, session.students[1])
    assert r.status_code == 409 and "harder questions" in r.json()["detail"]


def test_drafts_and_text_only_questions_are_never_chosen(client, session):  # noqa: F811
    calibrate_bank(session)
    draft = Item(strand_id=session.strand_id, question_text="Unchecked?", options=["a", "b"],
                 correct_option=0, status="draft", difficulty_b=-0.9, discrimination_a=1.0)
    spoken = Item(strand_id=session.strand_id, question_text="Say why.", status="approved",
                  difficulty_b=-0.9, discrimination_a=1.0)
    session.add_all([draft, spoken])
    session.commit()
    add_fresh(session)
    ids = {i["item_id"] for i in practise(client, session, session.students[5]).json()["items"]}
    assert str(draft.item_id) not in ids and str(spoken.item_id) not in ids


def test_a_length_outside_3_to_10_is_refused(client, session):  # noqa: F811
    assert practise(client, session, session.students[0], length=20).status_code == 422


def test_a_strand_the_class_does_not_use_is_not_found(client, session):  # noqa: F811
    other = Strand(name="Elsewhere", level="Upper Primary")
    session.add(other)
    session.commit()
    r = practise(client, session, session.students[0], strand_id=str(other.strand_id))
    assert r.status_code == 404


def test_another_schools_learner_is_not_found(client, session):  # noqa: F811
    calibrate_bank(session)
    add_fresh(session)
    rival = School(name="Rival", type="private")
    outsider = Teacher(name="R", email="r@x.y", password_hash="x", school=rival)
    session.add_all([rival, outsider])
    session.commit()
    r = client.post(f"/api/students/{session.students[0].student_id}/practice",
                    json={"strand_id": str(session.strand_id)}, headers=auth(outsider))
    assert r.status_code == 404
