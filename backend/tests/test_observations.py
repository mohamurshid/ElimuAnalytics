"""
Observed evidence: rubric levels from tasks a teacher watches.

What these hold, in the order observations.py states its rules: the KICD
rubric rows load once and refresh in place; the indicators offered for a
sub-strand are the curriculum's, best match first, plus the school's own;
the grid saves idempotently and all or nothing; the support list counts two
observed tasks short of Meets as its own signal; and the report prompt
carries the levels without inviting a quotation the grounding check would
refuse.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.db import get_session
from app.ingest_rubrics import ingest
from app.main import app
from app.models import (
    Classroom,
    ClassStrand,
    ObservationTask,
    RubricIndicator,
    RubricScore,
    School,
    Strand,
    Student,
    Teacher,
)
from app.observations import relevance, terms, tier_for_mean
from app.reports import LearnerFacts, build_prompt, observation_block
from app.security import ROLE_SCHOOL_ADMIN, create_token
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .test_repository import session  # noqa: F401 - pytest fixture

RUBRICS = [
    {"grade": "Grade 5", "subject": "Science and Technology",
     "indicator": "Describing functions of parts of a flower",
     "exceeds": "e", "meets": "m", "approaches": "a", "below": "b",
     "extraction_status": "OK"},
    {"grade": "Grade 5", "subject": "Science and Technology",
     "indicator": "Demonstrating the modes of heat transfer in nature",
     "exceeds": "Learner accurately demonstrates", "meets": "Learner demonstrates",
     "approaches": "Learner partially demonstrates", "below": "Learner demonstrates with help",
     "extraction_status": "OK"},
    {"grade": "Grade 5", "subject": "Science and Technology",
     "indicator": "Explaining the uses of heat transfer in day to day life",
     "exceeds": "e", "meets": "m", "approaches": "a", "below": "b",
     "extraction_status": "OK"},
    {"grade": "Grade 4", "subject": "Science and Technology",
     "indicator": "Demonstrating heat transfer in Grade 4",
     "exceeds": "e", "meets": "m", "approaches": "a", "below": "b",
     "extraction_status": "OK"},
    {"grade": "Grade 5", "subject": "Science and Technology",
     "indicator": "A row the extractor could not read",
     "extraction_status": "FAILED"},
]


@pytest.fixture
def client(session):  # noqa: F811
    strand = session.get(Strand, session.strand_id)
    strand.name = "3.0 Force and Energy / 3.3 Heat Transfer"
    strand.grade = "Grade 5"
    strand.learning_area = "Science and Technology"
    session.commit()
    ingest(session, RUBRICS)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def teacher(session) -> Teacher:  # noqa: F811
    return session.scalar(select(Teacher).where(Teacher.email == "t@x.y"))


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def the_class(session) -> Classroom:  # noqa: F811
    return session.scalar(select(Classroom))


def indicator(session, words: str) -> RubricIndicator:  # noqa: F811
    return session.scalar(
        select(RubricIndicator).where(RubricIndicator.indicator.contains(words))
    )


def make_task(client, session, *words, title="Heat transfer demonstration"):  # noqa: F811
    ids = [str(indicator(session, w).indicator_id) for w in (words or ("modes of heat",))]
    return client.post(
        f"/api/classrooms/{the_class(session).class_id}/observations",
        json={"strand_id": str(session.strand_id), "kind": "observation",
              "title": title, "indicator_ids": ids},
        headers=auth(teacher(session)),
    )


def save(client, session, task, scores):  # noqa: F811
    return client.put(f"/api/observations/{task['task_id']}/scores",
                      json={"scores": scores}, headers=auth(teacher(session)))


def level_all(client, session, task, level, learners=None):  # noqa: F811
    learners = learners or session.students[:3]
    return save(client, session, task, [
        {"student_id": str(s.student_id), "indicator_id": i["indicator_id"], "level": level}
        for s in learners for i in task["indicators"]
    ])


def another_school(session):  # noqa: F811
    school = School(name="Other School", type="private")
    other = Teacher(name="O", email="o@x.y", password_hash="x", school=school)
    room = Classroom(grade="Grade 5", school=school, teacher=other)
    pupil = Student(name="Elsewhere", classroom=room)
    session.add_all([school, other, room, pupil])
    session.flush()
    session.add(ClassStrand(class_id=room.class_id, strand_id=session.strand_id))
    session.commit()
    return other, room, pupil


# --- pure rules --------------------------------------------------------------
def test_words_are_stemmed_so_demonstrating_meets_demonstrate():
    assert "demonstrat" in terms("Demonstrating") and "demonstrat" in terms("demonstrates")
    assert "ability" not in terms("Ability to name")


def test_the_heat_transfer_indicators_rank_above_the_flower():
    name = "3.0 Force and Energy / 3.3 Heat Transfer"
    assert relevance(name, "Demonstrating the modes of heat transfer in nature") == 4
    assert relevance(name, "Describing functions of parts of a flower") == 0


@pytest.mark.parametrize(
    "mean, tier",
    [(4, "Exceeds expectation"), (3.5, "Exceeds expectation"), (3, "Meets expectation"),
     (2.5, "Meets expectation"), (2.4, "Approaches expectation"),
     (1.5, "Approaches expectation"), (1, "Below expectation")],
)
def test_a_mean_level_rounds_halves_up(mean, tier):
    assert tier_for_mean(mean) == tier


# --- loading the rubric -------------------------------------------------------
def test_rubric_rows_load_once_and_refresh_in_place(session):  # noqa: F811
    first = ingest(session, RUBRICS)
    assert first == {"added": 4, "updated": 0, "skipped": 1}
    changed = [dict(r) for r in RUBRICS]
    changed[1]["meets"] = "Learner demonstrates the three modes"
    again = ingest(session, changed)
    assert again == {"added": 0, "updated": 4, "skipped": 1}
    assert session.scalar(select(func.count()).select_from(RubricIndicator)) == 4
    assert indicator(session, "modes of heat").meets == "Learner demonstrates the three modes"


def test_a_reload_keeps_the_levels_recorded_against_an_indicator(client, session):  # noqa: F811
    task = make_task(client, session).json()
    level_all(client, session, task, 3)
    ingest(session, RUBRICS)
    assert session.scalar(select(func.count()).select_from(RubricScore)) == 3


# --- indicators offered -------------------------------------------------------
def test_the_strands_own_grade_and_area_are_offered_best_match_first(client, session):  # noqa: F811
    rows = client.get(f"/api/strands/{session.strand_id}/indicators",
                      headers=auth(teacher(session))).json()
    texts = [r["indicator"] for r in rows]
    assert len(rows) == 3  # not the Grade 4 row, not the unreadable one
    assert "flower" in texts[-1]
    assert [r["suggested"] for r in rows] == [True, True, False]


def test_a_teachers_indicator_is_offered_first_and_only_at_their_school(
    client, session  # noqa: F811
):
    r = client.post(f"/api/strands/{session.strand_id}/indicators",
                    json={"indicator": "Builds a working solar cooker in a group"},
                    headers=auth(teacher(session)))
    assert r.status_code == 201 and r.json()["source"] == "teacher"
    rows = client.get(f"/api/strands/{session.strand_id}/indicators",
                      headers=auth(teacher(session))).json()
    assert rows[0]["indicator"] == "Builds a working solar cooker in a group"

    other, _, _ = another_school(session)
    theirs = client.get(f"/api/strands/{session.strand_id}/indicators",
                        headers=auth(other)).json()
    assert "solar cooker" not in str(theirs)


def test_a_strand_no_class_at_the_school_uses_is_not_found(client, session):  # noqa: F811
    unused = Strand(name="Unused", level="Upper Primary")
    session.add(unused)
    session.commit()
    r = client.get(f"/api/strands/{unused.strand_id}/indicators", headers=auth(teacher(session)))
    assert r.status_code == 404


# --- making a task ------------------------------------------------------------
def test_a_task_is_made_with_the_indicators_in_the_order_chosen(client, session):  # noqa: F811
    r = make_task(client, session, "uses of heat", "modes of heat")
    assert r.status_code == 201
    task = r.json()
    assert [i["indicator"][:9] for i in task["indicators"]] == ["Explainin", "Demonstra"]
    assert len(task["learners"]) == 40 and task["scores"] == []


def test_an_indicator_from_another_grade_is_refused(client, session):  # noqa: F811
    assert make_task(client, session, "in Grade 4").status_code == 422


def test_more_than_five_indicators_or_an_unknown_kind_is_refused(client, session):  # noqa: F811
    one = str(indicator(session, "modes of heat").indicator_id)
    url = f"/api/classrooms/{the_class(session).class_id}/observations"
    base = {"strand_id": str(session.strand_id), "title": "T"}
    many = client.post(url, json={**base, "kind": "project", "indicator_ids": [one] * 6},
                       headers=auth(teacher(session)))
    odd = client.post(url, json={**base, "kind": "exam", "indicator_ids": [one]},
                      headers=auth(teacher(session)))
    assert many.status_code == 422 and odd.status_code == 422


def test_another_schools_class_is_not_found(client, session):  # noqa: F811
    _, room, _ = another_school(session)
    one = str(indicator(session, "modes of heat").indicator_id)
    r = client.post(f"/api/classrooms/{room.class_id}/observations",
                    json={"strand_id": str(session.strand_id), "kind": "project",
                          "title": "T", "indicator_ids": [one]},
                    headers=auth(teacher(session)))
    assert r.status_code == 404


# --- the grid -----------------------------------------------------------------
def test_saving_the_same_grid_twice_changes_nothing(client, session):  # noqa: F811
    task = make_task(client, session, "modes of heat", "uses of heat").json()
    assert level_all(client, session, task, 2).status_code == 200
    again = level_all(client, session, task, 2).json()
    assert len(again["scores"]) == 6
    assert session.scalar(select(func.count()).select_from(RubricScore)) == 6


def test_a_level_can_be_changed_and_cleared(client, session):  # noqa: F811
    task = make_task(client, session).json()
    pupil = str(session.students[0].student_id)
    ind = task["indicators"][0]["indicator_id"]
    save(client, session, task, [{"student_id": pupil, "indicator_id": ind, "level": 1,
                                  "note": "  needed  help  "}])
    out = save(client, session, task, [{"student_id": pupil, "indicator_id": ind,
                                        "level": 4}]).json()
    assert out["scores"][0]["level"] == 4 and out["scores"][0]["note"] is None
    cleared = save(client, session, task, [{"student_id": pupil, "indicator_id": ind,
                                            "level": None}]).json()
    assert cleared["scores"] == []


def test_one_bad_row_refuses_the_whole_save(client, session):  # noqa: F811
    task = make_task(client, session).json()
    _, _, stranger = another_school(session)
    ind = task["indicators"][0]["indicator_id"]
    good = {"student_id": str(session.students[0].student_id), "indicator_id": ind, "level": 3}
    r = save(client, session, task,
             [good, {"student_id": str(stranger.student_id), "indicator_id": ind, "level": 3}])
    assert r.status_code == 422
    unused = str(indicator(session, "flower").indicator_id)
    r = save(client, session, task, [good, {**good, "indicator_id": unused}])
    assert r.status_code == 422
    assert save(client, session, task, [{**good, "level": 5}]).status_code == 422
    assert session.scalar(select(func.count()).select_from(RubricScore)) == 0


def test_the_class_list_counts_learners_at_each_level(client, session):  # noqa: F811
    task = make_task(client, session).json()
    level_all(client, session, task, 1, session.students[:2])
    level_all(client, session, task, 3, session.students[2:5])
    rows = client.get(f"/api/classrooms/{the_class(session).class_id}/observations",
                      headers=auth(teacher(session))).json()
    assert rows[0]["learners_observed"] == 5
    assert rows[0]["levels"]["Below expectation"] == 2
    assert rows[0]["levels"]["Meets expectation"] == 3


def test_a_learners_levels_are_listed_and_scoped_to_the_school(client, session):  # noqa: F811
    task = make_task(client, session).json()
    level_all(client, session, task, 2)
    pupil = session.students[0].student_id
    mine = client.get(f"/api/students/{pupil}/observations", headers=auth(teacher(session)))
    assert mine.json()[0]["tier"] == "Approaches expectation"
    other, _, _ = another_school(session)
    theirs = client.get(f"/api/students/{pupil}/observations", headers=auth(other))
    assert theirs.status_code == 404


def test_only_the_maker_or_a_head_teacher_removes_a_task(client, session):  # noqa: F811
    task = make_task(client, session).json()
    level_all(client, session, task, 3)
    colleague = Teacher(name="C", email="c@x.y", password_hash="x",
                        school_id=teacher(session).school_id)
    head = Teacher(name="H", email="h@x.y", password_hash="x", role=ROLE_SCHOOL_ADMIN,
                   school_id=teacher(session).school_id)
    session.add_all([colleague, head])
    session.commit()
    url = f"/api/observations/{task['task_id']}"
    assert client.delete(url, headers=auth(colleague)).status_code == 403
    assert client.delete(url, headers=auth(head)).status_code == 204
    assert session.scalar(select(func.count()).select_from(RubricScore)) == 0


# --- the support list ---------------------------------------------------------
def _age(session, task, days):  # noqa: F811
    row = session.get(ObservationTask, uuid.UUID(task["task_id"]))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    session.commit()


def observation_rows(client, session):  # noqa: F811
    rows = client.get("/api/flags", headers=auth(teacher(session))).json()
    return [r for r in rows if r["source"] == "observation"]


def test_two_observed_tasks_short_of_meets_add_a_learner(client, session):  # noqa: F811
    first = make_task(client, session, title="First").json()
    _age(session, first, 7)
    second = make_task(client, session, title="Second").json()
    pupil = session.students[:1]
    level_all(client, session, first, 2, pupil)
    assert observation_rows(client, session) == []  # once is not enough
    level_all(client, session, second, 1, pupil)
    rows = observation_rows(client, session)
    assert len(rows) == 1
    assert rows[0]["severity"] == "Below expectation"
    assert rows[0]["tasks"] == ["First", "Second"]


def test_a_task_at_meets_after_a_low_one_adds_no_one(client, session):  # noqa: F811
    first = make_task(client, session, title="First").json()
    _age(session, first, 7)
    second = make_task(client, session, title="Second").json()
    pupil = session.students[:1]
    level_all(client, session, first, 1, pupil)
    level_all(client, session, second, 3, pupil)
    assert observation_rows(client, session) == []


def test_correcting_a_level_takes_the_learner_off_again(client, session):  # noqa: F811
    first = make_task(client, session, title="First").json()
    _age(session, first, 7)
    second = make_task(client, session, title="Second").json()
    pupil = session.students[:1]
    level_all(client, session, first, 2, pupil)
    level_all(client, session, second, 2, pupil)
    assert len(observation_rows(client, session)) == 1
    level_all(client, session, second, 3, pupil)
    assert observation_rows(client, session) == []


# --- the report prompt ------------------------------------------------------
FACTS = LearnerFacts(name="Chebet", grade="Grade 5", strand="Force and Energy",
                     sub_strand="Heat Transfer", theta=-1.2, tier="Below expectation",
                     items_answered=12, consecutive_flags=2)
OBSERVED = [{"title": "Heat transfer demonstration", "kind": "observation",
             "observed_at": datetime(2026, 11, 16), "indicator":
             "Demonstrating the modes of heat transfer in nature",
             "tier": "Approaches expectation", "note": "Named conduction only"}]


def test_no_observations_leaves_the_prompt_exactly_as_it_was():
    assert observation_block(None) == "" and observation_block([]) == ""
    assert build_prompt(FACTS, ["ctx"]) == build_prompt(FACTS, ["ctx"], observations=[])


def test_observed_levels_reach_the_prompt_without_inviting_a_quotation():
    prompt = build_prompt(FACTS, ["ctx"], observations=OBSERVED)
    assert "CLASSROOM OBSERVATIONS" in prompt
    assert "modes of heat transfer in nature - Approaches expectation" in prompt
    assert "teacher's note: Named conduction only" in prompt
    assert "do NOT put quotation marks around any of this section" in prompt
