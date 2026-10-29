"""
Question statuses, review and versions.

The property that matters most is the first one tested: nothing but an
approved question reaches a learner's device, and no question's key or mark
scheme ever does. The quiz endpoint is the only door to the device, so the
tests look at its raw response text, not just its parsed fields - a key
smuggled in under another name would pass a field check.

Then: a reported question stops counting until a head teacher looks at it,
and editing an answered question makes a new version rather than rewriting
what learners answered.
"""

from __future__ import annotations

import pytest
from app.db import get_session
from app.item_status import mcq_problems
from app.main import app
from app.models import Classroom, Item, Response, Teacher
from app.repository import build_response_matrix
from app.security import ROLE_SCHOOL_ADMIN, create_token
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .test_repository import session  # noqa: F401 - pytest fixture

OPTIONS = ["Conduction", "Convection", "Radiation", "Evaporation"]
MISCONCEPTIONS = [None, "thinks heat only moves through liquids",
                  "thinks every heat transfer is radiation", "confuses heat with water loss"]
SECRET = "MARKER-RATIONALE-MUST-NOT-LEAK"


@pytest.fixture
def client(session):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def teacher(session) -> Teacher:  # noqa: F811
    t = session.scalar(select(Teacher))
    assert t.role == "teacher"
    return t


@pytest.fixture
def head(session, teacher) -> Teacher:  # noqa: F811
    h = Teacher(name="Head", email="head@x.y", password_hash="x",
                role=ROLE_SCHOOL_ADMIN, school_id=teacher.school_id)
    session.add(h)
    session.commit()
    return h


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def draft(session, text="Which way does heat travel along a metal spoon?") -> Item:  # noqa: F811
    item = Item(
        strand_id=session.strand_id, question_text=text, options=OPTIONS,
        correct_option=0, rationale=SECRET, misconceptions=MISCONCEPTIONS,
        status="draft", source="ai",
    )
    session.add(item)
    session.commit()
    return item


def answered_item(session) -> Item:  # noqa: F811
    return session.scalars(select(Item).where(Item.source == "teacher")).first()


def quiz(client, session, who):  # noqa: F811
    classroom = session.scalar(select(Classroom))
    return client.get(f"/api/assessments/quiz/{classroom.class_id}/{session.strand_id}",
                      headers=auth(who))


def items_in_matrix(session) -> int:  # noqa: F811
    matrix, _, _ = build_response_matrix(session, session.strand_id)
    return matrix.shape[0]


# --- what reaches a learner's device ---------------------------------------
@pytest.mark.parametrize("status", ["draft", "reported", "rejected", "retired"])
def test_only_approved_questions_are_served(client, session, teacher, status):  # noqa: F811
    item = draft(session)
    item.status = status
    session.commit()

    r = quiz(client, session, teacher)
    assert r.status_code == 200
    served = {q["item_id"] for q in r.json()["items"]}
    assert str(item.item_id) not in served
    assert len(served) == 12


def test_no_key_or_mark_scheme_ever_reaches_the_device(client, session, teacher):  # noqa: F811
    item = draft(session)
    client.post(f"/api/items/{item.item_id}/approve", headers=auth(teacher))

    r = quiz(client, session, teacher)
    assert str(item.item_id) in {q["item_id"] for q in r.json()["items"]}
    raw = r.text
    for leak in ("correct_option", "misconception", "rationale", SECRET,
                 MISCONCEPTIONS[1], "curriculum_excerpt"):
        assert leak not in raw, leak


# --- what counts toward levels ---------------------------------------------
def test_a_reported_question_stops_counting_until_approved_again(
    client, session, teacher, head  # noqa: F811
):
    item = answered_item(session)
    answers = session.scalar(select(func.count()).select_from(Response))
    assert items_in_matrix(session) == 12

    r = client.post(f"/api/items/{item.item_id}/report", headers=auth(teacher),
                    json={"reason": "Option B is also correct"})
    assert r.status_code == 200 and r.json()["status"] == "reported"
    assert r.json()["report_reason"] == "Option B is also correct"
    assert items_in_matrix(session) == 11
    assert session.scalar(select(func.count()).select_from(Response)) == answers

    assert client.post(f"/api/items/{item.item_id}/approve",
                       headers=auth(teacher)).status_code == 403
    assert client.post(f"/api/items/{item.item_id}/approve",
                       headers=auth(head)).status_code == 200
    assert items_in_matrix(session) == 12


def test_a_draft_does_not_count_and_does_not_fill_a_strand(client, session, teacher):  # noqa: F811
    draft(session)
    assert items_in_matrix(session) == 12
    strands = client.get("/api/strands", headers=auth(teacher)).json()
    assert strands[0]["active_items"] == 12
    assert strands[0]["draft_items"] == 1


# --- review ----------------------------------------------------------------
def test_any_teacher_approves_or_rejects_a_draft(client, session, teacher):  # noqa: F811
    one, two = draft(session), draft(session, "Why do pans have plastic handles?")
    a = client.post(f"/api/items/{one.item_id}/approve", headers=auth(teacher))
    b = client.post(f"/api/items/{two.item_id}/reject", headers=auth(teacher))
    assert (a.json()["status"], b.json()["status"]) == ("approved", "rejected")
    session.refresh(one)
    assert one.reviewed_by == teacher.teacher_id and one.reviewed_at is not None


def test_a_rejected_draft_is_kept_for_the_approval_rate(client, session, teacher):  # noqa: F811
    item = draft(session)
    client.post(f"/api/items/{item.item_id}/reject", headers=auth(teacher))
    assert session.get(Item, item.item_id) is not None
    listed = client.get("/api/items", params={"status": "rejected"}, headers=auth(teacher))
    assert [i["item_id"] for i in listed.json()] == [str(item.item_id)]


def test_a_report_needs_a_reason_and_an_approved_question(client, session, teacher):  # noqa: F811
    item = answered_item(session)
    url = f"/api/items/{item.item_id}/report"
    assert client.post(url, headers=auth(teacher), json={"reason": ""}).status_code == 422
    assert client.post(url, headers=auth(teacher), json={"reason": "Two right answers"}
                       ).status_code == 200
    # Already reported.
    assert client.post(url, headers=auth(teacher), json={"reason": "Again, still wrong"}
                       ).status_code == 409


def test_only_a_head_teacher_retires(client, session, teacher, head):  # noqa: F811
    item = answered_item(session)
    url = f"/api/items/{item.item_id}/retire"
    assert client.post(url, headers=auth(teacher)).status_code == 403
    r = client.post(url, headers=auth(head))
    assert r.status_code == 200 and r.json()["status"] == "retired"
    assert client.post(f"/api/items/{item.item_id}/approve",
                       headers=auth(head)).status_code == 409


def test_a_draft_with_a_broken_key_cannot_be_approved(client, session, teacher):  # noqa: F811
    item = draft(session)
    item.correct_option = 7
    session.commit()
    r = client.post(f"/api/items/{item.item_id}/approve", headers=auth(teacher))
    assert r.status_code == 422
    assert "not one of the options" in str(r.json()["detail"])


# --- editing and versions --------------------------------------------------
def test_a_draft_is_edited_in_place_and_stays_a_draft(client, session, teacher):  # noqa: F811
    item = draft(session)
    r = client.patch(f"/api/items/{item.item_id}", headers=auth(teacher),
                     json={"question_text": "Which way does heat move along a spoon?"})
    assert r.status_code == 200
    assert r.json()["item_id"] == str(item.item_id)
    assert r.json()["status"] == "draft"
    assert r.json()["version"] == 1


def test_editing_an_answered_question_makes_a_new_version(client, session, head):  # noqa: F811
    old = answered_item(session)
    answers = session.scalar(
        select(func.count()).select_from(Response).where(Response.item_id == old.item_id)
    )
    assert answers > 0

    r = client.patch(f"/api/items/{old.item_id}", headers=auth(head),
                     json={"question_text": old.question_text + " (reworded)"})
    assert r.status_code == 200
    new = r.json()
    assert new["item_id"] != str(old.item_id)
    assert new["version"] == 2
    assert new["previous_item_id"] == str(old.item_id)
    assert new["status"] == "approved"
    assert new["difficulty_b"] is None  # uncalibrated: nobody has answered it

    session.refresh(old)
    assert old.status == "retired"
    assert session.scalar(
        select(func.count()).select_from(Response).where(Response.item_id == old.item_id)
    ) == answers


def test_retired_and_rejected_questions_cannot_be_edited(client, session, teacher):  # noqa: F811
    item = draft(session)
    client.post(f"/api/items/{item.item_id}/reject", headers=auth(teacher))
    r = client.patch(f"/api/items/{item.item_id}", headers=auth(teacher),
                     json={"question_text": "Trying to revive it?"})
    assert r.status_code == 409


# --- the list --------------------------------------------------------------
def test_the_list_shows_approved_questions_unless_asked(client, session, teacher):  # noqa: F811
    draft(session)
    default = client.get("/api/items", headers=auth(teacher)).json()
    assert {i["status"] for i in default} == {"approved"}
    drafts = client.get("/api/items", params={"status": "draft"}, headers=auth(teacher))
    assert len(drafts.json()) == 1
    assert drafts.json()[0]["misconceptions"] == MISCONCEPTIONS  # teachers see the scheme
    assert client.get("/api/items", params={"status": "pending"},
                      headers=auth(teacher)).status_code == 422


# --- the shape of a multiple-choice question -------------------------------
@pytest.mark.parametrize(
    "options, key, misconceptions, problem",
    [
        (["A"], 0, None, "2 to 6 options"),
        (["A", "a"], 0, None, "two options are the same"),
        (["A", " "], 0, None, "an option is empty"),
        (["A", "B"], 2, None, "not one of the options"),
        (["A", "B"], None, None, "given together"),
        (["A", "B"], 0, [None], "one misconception entry per option"),
        (["A", "B"], 0, ["wrong", None], "correct option cannot carry"),
    ],
)
def test_malformed_questions_are_described(options, key, misconceptions, problem):
    assert any(problem in p for p in mcq_problems(options, key, misconceptions))


@pytest.mark.parametrize(
    "options",
    [
        ["con-FLICT", "CON-flict", "con-flict"],  # word stress: the capitals are the answer
        ["SUB-ject (noun)", "sub-JECT (noun)"],
        ["Copper", "COPPER"],
    ],
)
def test_capitals_inside_a_word_make_options_different(options):
    assert "two options are the same" not in mcq_problems(options, 0)


@pytest.mark.parametrize(
    "options",
    [["Copper", "copper"], ["the Sun", "The sun"], ["heat  energy", "Heat energy"]],
)
def test_a_capital_at_the_start_of_a_word_does_not(options):
    assert "two options are the same" in mcq_problems(options, 0)


def test_a_text_only_question_is_still_valid_for_paper_marking():
    assert mcq_problems(None, None) == []
    assert mcq_problems(OPTIONS, 0, MISCONCEPTIONS) == []
