"""
Assessment recording tests.

The endpoint's job is not "insert rows". It is to be safe to call twice.

A tablet that submits a class's work and loses the connection before the reply
arrives does not know whether the work landed, so it retries. If the server
treats the retry as new, every response in that batch is recorded a second
time - which does not raise an error, it overwrites cells in the response
matrix and moves ability estimates. Idempotency is therefore the property
under test here, not a nicety.

The rejection paths matter for the same reason. Every one of them describes a
way to end up with a plausible wrong number rather than a visible failure.
"""

from __future__ import annotations

import uuid

import pytest
from app.db import get_session
from app.main import app
from app.models import AssessmentBatch, Classroom, Item, Response, School, Student, Teacher
from app.security import ROLE_SCHOOL_ADMIN, create_token, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import func, select

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


@pytest.fixture
def fresh(session, head):  # noqa: F811
    """A learner and an item with no response between them.

    The seeded classroom is fully answered, so a clean pair has to be made.
    """
    classroom = session.scalar(select(Classroom))
    learner = Student(name="New Learner", class_id=classroom.class_id)
    item = session.scalar(select(Item))
    session.add(learner)
    session.commit()
    session.refresh(learner)
    return {"classroom": classroom, "learner": learner, "item": item}


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def batch_body(fresh, client_batch_id=None, responses=None) -> dict:
    return {
        "client_batch_id": str(client_batch_id or uuid.uuid4()),
        "class_id": str(fresh["classroom"].class_id),
        "strand_id": str(session_strand(fresh)),
        "responses": responses
        if responses is not None
        else [
            {
                "student_id": str(fresh["learner"].student_id),
                "item_id": str(fresh["item"].item_id),
                "correct": True,
            }
        ],
    }


def session_strand(fresh) -> uuid.UUID:
    return fresh["item"].strand_id


def count_responses(session) -> int:  # noqa: F811
    return int(session.scalar(select(func.count()).select_from(Response)) or 0)


# --- the happy path --------------------------------------------------------
def test_a_batch_is_recorded(client, head, fresh, session):  # noqa: F811
    before = count_responses(session)
    r = client.post("/api/assessments", headers=auth(head), json=batch_body(fresh))

    assert r.status_code == 200
    body = r.json()
    assert body["duplicate"] is False
    assert body["responses_recorded"] == 1
    assert count_responses(session) == before + 1


def test_recorded_responses_reach_the_matrix(client, head, fresh, session):  # noqa: F811
    """A recorded response must change what calibration sees, or the endpoint
    has written rows that do not matter."""
    from app.repository import build_response_matrix
    from girth import INVALID_RESPONSE

    strand_id = session_strand(fresh)
    before, item_ids, student_ids = build_response_matrix(session, strand_id)
    row = item_ids.index(fresh["item"].item_id)
    col = student_ids.index(fresh["learner"].student_id)
    assert before[row, col] == INVALID_RESPONSE  # unanswered to begin with

    client.post("/api/assessments", headers=auth(head), json=batch_body(fresh))

    after, item_ids, student_ids = build_response_matrix(session, strand_id)
    row = item_ids.index(fresh["item"].item_id)
    col = student_ids.index(fresh["learner"].student_id)
    assert after[row, col] == 1  # the recorded answer, as an integer


# --- idempotency -----------------------------------------------------------
def test_the_same_batch_twice_records_once(client, head, fresh, session):  # noqa: F811
    """The property the whole endpoint exists for."""
    body = batch_body(fresh)

    first = client.post("/api/assessments", headers=auth(head), json=body)
    after_first = count_responses(session)
    second = client.post("/api/assessments", headers=auth(head), json=body)

    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert count_responses(session) == after_first


def test_a_retry_is_not_an_error(client, head, fresh):
    """The device did nothing wrong, and the outcome it wanted has happened.
    Answering 4xx would make a correct client look broken."""
    body = batch_body(fresh)
    client.post("/api/assessments", headers=auth(head), json=body)
    assert client.post("/api/assessments", headers=auth(head), json=body).status_code == 200


def test_a_device_can_ask_whether_a_batch_landed(client, head, fresh):
    body = batch_body(fresh)
    client.post("/api/assessments", headers=auth(head), json=body)

    r = client.get(f"/api/assessments/{body['client_batch_id']}", headers=auth(head))
    assert r.status_code == 200
    assert r.json()["responses_recorded"] == 1

    assert client.get(f"/api/assessments/{uuid.uuid4()}", headers=auth(head)).status_code == 404


# --- rejections ------------------------------------------------------------
def test_re_answering_an_item_is_refused(client, head, fresh, session):  # noqa: F811
    """One cell per learner and item. A second answer would overwrite the
    first and silently change estimates derived from it."""
    answered = session.scalar(select(Response))
    body = batch_body(
        fresh,
        responses=[{
            "student_id": str(answered.student_id),
            "item_id": str(answered.item_id),
            "correct": False,
        }],
    )
    r = client.post("/api/assessments", headers=auth(head), json=body)
    assert r.status_code == 409
    assert "already answered" in str(r.json()["detail"]["problems"])


def test_a_duplicate_inside_one_batch_is_refused(client, head, fresh):
    one = {
        "student_id": str(fresh["learner"].student_id),
        "item_id": str(fresh["item"].item_id),
        "correct": True,
    }
    r = client.post(
        "/api/assessments", headers=auth(head), json=batch_body(fresh, responses=[one, one])
    )
    assert r.status_code == 422
    assert "twice" in str(r.json()["detail"]["problems"])


def test_a_withdrawn_item_is_refused(client, head, fresh, session):  # noqa: F811
    """A withdrawn item is out of the calibration pool, so a response to it
    would be recorded and then never counted."""
    fresh["item"].is_active = False
    session.commit()

    r = client.post("/api/assessments", headers=auth(head), json=batch_body(fresh))
    assert r.status_code == 422
    assert "withdrawn" in str(r.json()["detail"]["problems"])


def test_a_learner_from_another_class_is_refused(client, head, fresh, session):  # noqa: F811
    other_class = Classroom(
        grade="Grade 4", name="Red",
        school_id=fresh["classroom"].school_id,
        teacher_id=head.teacher_id,
    )
    outsider = Student(name="Elsewhere", classroom=other_class)
    session.add_all([other_class, outsider])
    session.commit()
    session.refresh(outsider)

    r = client.post(
        "/api/assessments",
        headers=auth(head),
        json=batch_body(fresh, responses=[{
            "student_id": str(outsider.student_id),
            "item_id": str(fresh["item"].item_id),
            "correct": True,
        }]),
    )
    assert r.status_code == 422
    assert "not enrolled" in str(r.json()["detail"]["problems"])


def test_nothing_is_written_when_the_batch_is_rejected(client, head, fresh, session):  # noqa: F811
    """All or nothing. A partly-recorded batch is the worst outcome: the
    device cannot safely retry it and the data is half there."""
    before = count_responses(session)
    good = {
        "student_id": str(fresh["learner"].student_id),
        "item_id": str(fresh["item"].item_id),
        "correct": True,
    }
    bad = {"student_id": str(uuid.uuid4()), "item_id": str(fresh["item"].item_id), "correct": True}

    body = batch_body(fresh, responses=[good, bad])
    r = client.post("/api/assessments", headers=auth(head), json=body)
    assert r.status_code == 422
    assert count_responses(session) == before
    assert session.scalar(select(func.count()).select_from(AssessmentBatch)) == 0


def test_another_schools_classroom_is_not_found(client, head, fresh, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    session.add_all([rival_school, rival_class])
    session.commit()
    session.refresh(rival_class)

    body = batch_body(fresh)
    body["class_id"] = str(rival_class.class_id)
    r = client.post("/api/assessments", headers=auth(head), json=body)
    assert r.status_code == 404


def test_recording_requires_authentication(client, fresh):
    assert client.post("/api/assessments", json=batch_body(fresh)).status_code == 401


# --- which pairs are already taken -----------------------------------------
def test_answered_pairs_lists_what_is_already_recorded(client, head, fresh, session):  # noqa: F811
    """A marking grid cannot be honest without this.

    Without it the interface shows every cell as free, a teacher ticks one
    that is already recorded, and the whole batch is refused with a 409
    naming pairs they had no way of knowing about.
    """
    cid = fresh["classroom"].class_id
    sid = session_strand(fresh)

    r = client.get(f"/api/assessments/answered/{cid}/{sid}", headers=auth(head))
    assert r.status_code == 200
    before = set(r.json()["answered"])
    assert len(before) == 471  # the seeded responses

    pair = f"{fresh['learner'].student_id}:{fresh['item'].item_id}"
    assert pair not in before  # the fresh learner has answered nothing

    client.post("/api/assessments", headers=auth(head), json=batch_body(fresh))

    after = set(
        client.get(f"/api/assessments/answered/{cid}/{sid}", headers=auth(head))
        .json()["answered"]
    )
    assert pair in after
    assert len(after) == len(before) + 1


def test_answered_pairs_is_school_scoped(client, head, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    session.add_all([rival_school, rival_class])
    session.commit()
    session.refresh(rival_class)

    strand = session.scalar(select(Item)).strand_id
    r = client.get(
        f"/api/assessments/answered/{rival_class.class_id}/{strand}",
        headers=auth(head),
    )
    assert r.status_code == 404


def test_answered_pairs_requires_authentication(client, fresh):
    cid = fresh["classroom"].class_id
    sid = session_strand(fresh)
    assert client.get(f"/api/assessments/answered/{cid}/{sid}").status_code == 401


# --- learner-facing delivery and marking ------------------------------------
def test_the_answer_key_never_leaves_the_server(client, head, fresh):
    """The control the whole learner-facing mode rests on.

    If the key reaches the browser, a curious learner can read it off the
    network tab, and a dishonest client can mark its own answers. The
    delivery schema has no field for it at all.
    """
    cid = fresh["classroom"].class_id
    sid = session_strand(fresh)

    r = client.get(f"/api/assessments/quiz/{cid}/{sid}", headers=auth(head))
    assert r.status_code == 200
    body = r.json()

    assert body["items"], "expected deliverable items"
    for item in body["items"]:
        assert set(item) == {"item_id", "question_text", "options"}
        assert len(item["options"]) == 4
    assert "correct" not in r.text.lower().replace("correctness", "")


def test_an_item_without_options_is_not_delivered(client, head, fresh, session):  # noqa: F811
    """A teacher can still mark it; a learner cannot answer it, because
    nothing knows what the right answer is."""
    cid = fresh["classroom"].class_id
    sid = session_strand(fresh)
    fresh["item"].options = None
    fresh["item"].correct_option = None
    session.commit()

    body = client.get(f"/api/assessments/quiz/{cid}/{sid}", headers=auth(head)).json()
    assert str(fresh["item"].item_id) not in [i["item_id"] for i in body["items"]]


def test_the_server_marks_a_learners_answer(client, head, fresh, session):  # noqa: F811
    """The device sends the option chosen; the server decides."""
    key = fresh["item"].correct_option
    body = batch_body(
        fresh,
        responses=[{
            "student_id": str(fresh["learner"].student_id),
            "item_id": str(fresh["item"].item_id),
            "selected_option": key,
        }],
    )
    assert client.post("/api/assessments", headers=auth(head), json=body).status_code == 200

    stored = session.scalar(
        select(Response).where(
            Response.student_id == fresh["learner"].student_id,
            Response.item_id == fresh["item"].item_id,
        )
    )
    assert stored.correctness is True
    assert stored.selected_option == key


def test_a_wrong_option_is_marked_wrong_and_remembered(client, head, fresh, session):  # noqa: F811
    """Which wrong answer was chosen is kept: it is the evidence behind
    distractor analysis, and it cannot be recovered afterwards."""
    wrong = (fresh["item"].correct_option + 1) % len(fresh["item"].options)
    body = batch_body(
        fresh,
        responses=[{
            "student_id": str(fresh["learner"].student_id),
            "item_id": str(fresh["item"].item_id),
            "selected_option": wrong,
        }],
    )
    client.post("/api/assessments", headers=auth(head), json=body)

    stored = session.scalar(
        select(Response).where(
            Response.student_id == fresh["learner"].student_id,
            Response.item_id == fresh["item"].item_id,
        )
    )
    assert stored.correctness is False
    assert stored.selected_option == wrong


def test_an_answer_must_be_one_thing_or_the_other(client, head, fresh):
    """Both, or neither, is a client bug worth refusing loudly."""
    base = {
        "student_id": str(fresh["learner"].student_id),
        "item_id": str(fresh["item"].item_id),
    }
    both = client.post(
        "/api/assessments",
        headers=auth(head),
        json=batch_body(fresh, responses=[{**base, "correct": True, "selected_option": 0}]),
    )
    neither = client.post(
        "/api/assessments",
        headers=auth(head),
        json=batch_body(fresh, responses=[base]),
    )
    assert both.status_code == 422
    assert neither.status_code == 422


def test_an_option_that_does_not_exist_is_refused(client, head, fresh):
    r = client.post(
        "/api/assessments",
        headers=auth(head),
        json=batch_body(fresh, responses=[{
            "student_id": str(fresh["learner"].student_id),
            "item_id": str(fresh["item"].item_id),
            "selected_option": 99,
        }]),
    )
    assert r.status_code == 422
    assert "does not exist" in str(r.json()["detail"]["problems"])


def test_quiz_delivery_is_school_scoped(client, head, session):  # noqa: F811
    rival_school = School(name="Rival", type="private")
    rival_class = Classroom(grade="Grade 4", name="Red", school=rival_school)
    session.add_all([rival_school, rival_class])
    session.commit()
    session.refresh(rival_class)

    strand = session.scalar(select(Item)).strand_id
    r = client.get(
        f"/api/assessments/quiz/{rival_class.class_id}/{strand}", headers=auth(head)
    )
    assert r.status_code == 404
