"""
Question generation.

The model is always a stub: these tests spend nothing and never reach the
network. They pin what the server does with whatever the model says -
because the model is not trusted, that is where the safety is:

  * everything generated is a DRAFT, and drafts never reach a learner
  * a question that fails a check is dropped and the reason recorded, never
    saved and never quietly repaired
  * the daily cap holds, and a failed run does not use it up
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from app import generation
from app.catalogue import catalogue_rows
from app.db import get_session
from app.main import app
from app.models import Classroom, GenerationRun, Item, School, Strand, Teacher
from app.questions import SubStrand, build_prompt, question_problems, shuffle_options
from app.reports import set_generator
from app.security import create_token
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from .test_catalogue import corpus_rows  # noqa: F401 - pytest fixture
from .test_repository import session  # noqa: F401 - pytest fixture

HEAT = "Grade 5|Science and Technology|3.0|3.3"
EXCERPT = "carry out experiments to identify good and poor conductors of heat"


WRONG = ["thinks hard things pass heat", "thinks kitchen things pass heat",
         "thinks thick things pass heat"]


def good(text="Which of these is a good conductor of heat?", key=0) -> dict:
    """In the model's shape: each option carries its own misconception."""
    wrong = iter(WRONG)
    options = [{"text": t, "misconception": "" if i == key else next(wrong)}
               for i, t in enumerate(["Copper", "Wood", "Plastic", "Cloth"])]
    return {"question": text, "options": options, "correct_option": key,
            "rationale": "Metals such as copper let heat through quickly.",
            "excerpt": EXCERPT}


def with_option(q: dict, index: int, **change) -> dict:
    options = [dict(o) for o in q["options"]]
    options[index].update(change)
    return {**q, "options": options}


def answer(questions, stop_reason="end_turn", raw=None):
    text = raw if raw is not None else json.dumps({"questions": questions})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1800, output_tokens=2500,
                              output_tokens_details=None),
    )


@pytest.fixture
def model():
    """A stub model that records what it was sent and says what it is told."""
    calls: list[dict] = []
    reply = {"value": answer([good()])}

    def generator(**kwargs):
        calls.append(kwargs)
        if isinstance(reply["value"], Exception):
            raise reply["value"]
        return reply["value"]

    set_generator(generator)
    yield SimpleNamespace(calls=calls, reply=reply)
    set_generator(None)


@pytest.fixture
def heat(session):  # noqa: F811
    strand = session.scalar(select(Strand))
    strand.grade, strand.learning_area, strand.curriculum_key = (
        "Grade 5", "Science and Technology", HEAT)
    session.commit()
    return strand


@pytest.fixture
def client(session, corpus_rows, monkeypatch):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[catalogue_rows] = lambda: corpus_rows
    monkeypatch.setattr("app.generation.worker_session",
                        lambda: SASession(session.get_bind()))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def teacher(session) -> Teacher:  # noqa: F811
    return session.scalar(select(Teacher))


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def run(client, session, strand, body=None):  # noqa: F811
    """Ask for questions, then read back the finished run."""
    r = client.post(f"/api/strands/{strand.strand_id}/generate", json=body,
                    headers=auth(teacher(session)))
    if r.status_code != 202:
        return r
    assert r.json()["status"] == "pending"
    return client.get(f"/api/generation-runs/{r.json()['run_id']}",
                      headers=auth(teacher(session)))


def drafts(session):  # noqa: F811
    session.expire_all()
    return list(session.scalars(select(Item).where(Item.source == "ai")))


# --- what is saved ---------------------------------------------------------
def test_generated_questions_are_saved_as_drafts_and_never_served(
    client, session, heat, model  # noqa: F811
):
    model.reply["value"] = answer([good(), good("Which of these is a poor conductor?", 1)])
    body = run(client, session, heat).json()

    assert body["status"] == "ready"
    assert body["produced"] == 2 and body["dropped"] == []
    saved = drafts(session)
    assert {i.status for i in saved} == {"draft"}
    assert all(i.generation_run_id is not None for i in saved)
    for item in saved:  # the key carries no misconception, wherever it landed
        assert item.misconceptions[item.correct_option] is None
    assert saved[0].curriculum_excerpt == EXCERPT
    assert saved[0].curriculum_source_row is not None

    classroom = session.scalar(select(Classroom))
    quiz = client.get(f"/api/assessments/quiz/{classroom.class_id}/{heat.strand_id}",
                      headers=auth(teacher(session))).json()
    assert len(quiz["items"]) == 12  # the seeded twelve, no drafts


def test_the_run_records_its_cost(client, session, heat, model):  # noqa: F811
    run(client, session, heat)
    r = session.scalar(select(GenerationRun))
    session.refresh(r)
    assert (r.input_tokens, r.output_tokens) == (1800, 2500)
    assert r.cost_usd == pytest.approx(1800 / 1e6 * 0.10 + 2500 / 1e6 * 0.50)
    assert r.model and r.effort == "medium"


# --- what the model is sent ------------------------------------------------
def test_the_model_writes_from_the_sub_strand_and_is_held_to_a_schema(
    client, session, heat, model  # noqa: F811
):
    run(client, session, heat, body={"count": 3})
    call = model.calls[0]
    prompt = call["messages"][0]["content"]
    assert "make oven gloves" in prompt  # the Grade 5 heat transfer design itself
    assert "Write 3 questions" in prompt
    assert "Grade 5" in prompt
    # The bank's existing questions are named, so they are not repeated.
    seeded = session.scalars(select(Item.question_text)).first()
    assert seeded in prompt
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_a_kiswahili_strand_is_written_in_kiswahili():
    sub = SubStrand("Grade 5", "Kiswahili", "Kusoma", "1.2.1", "Kusoma kwa Ufahamu",
                    "Kiswahili")
    assert "Kiswahili sanifu" in build_prompt(sub, ["maandishi"], 5)


# --- checks ----------------------------------------------------------------
@pytest.mark.parametrize(
    "flawed, problem",
    [
        (lambda q: {**q, "options": q["options"][:3]}, "not 4"),
        (lambda q: {**q, "correct_option": 9}, "not one of the options"),
        (lambda q: {**q, "question": "Copper is the answer. Which conducts heat best: copper?"},
         "contains its own answer"),
        (lambda q: {**q, "excerpt": "learners should build a solar oven from foil"},
         "not in the curriculum text"),
        (lambda q: with_option(q, 1, misconception=""), "no misconception"),
        (lambda q: with_option(q, 0, misconception="thinks metal is cold"),
         "cannot carry a misconception"),
        (lambda q: with_option(q, 2, text="copper"), "two options are the same"),
        (lambda q: {**q, "rationale": " "}, "no rationale"),
    ],
)
def test_a_flawed_question_is_described(flawed, problem, corpus_rows):  # noqa: F811
    texts = [r.syllabus_text for r in corpus_rows
             if r.grade == "Grade 5" and (r.sub_strand or "").startswith("3.3")]
    found = question_problems(flawed(good()), texts)
    assert any(problem in p for p in found), found


def test_a_sound_question_passes(corpus_rows):  # noqa: F811
    texts = [r.syllabus_text for r in corpus_rows
             if r.grade == "Grade 5" and (r.sub_strand or "").startswith("3.3")]
    assert question_problems(good(), texts) == []


def test_flawed_questions_are_dropped_with_reasons(client, session, heat, model):  # noqa: F811
    seeded = session.scalars(select(Item.question_text)).first()
    model.reply["value"] = answer([
        good(),
        {**good("Which one carries heat fastest?"), "excerpt": "an invented quotation here"},
        good(seeded),
    ])
    body = run(client, session, heat).json()
    assert body["produced"] == 1
    reasons = [p for d in body["dropped"] for p in d["problems"]]
    assert any("not in the curriculum text" in p for p in reasons)
    assert any("repeats a question already in the bank" in p for p in reasons)
    assert len(drafts(session)) == 1


def test_a_near_copy_is_dropped(client, session, heat, model, monkeypatch):  # noqa: F811
    """Two wordings the embedder places together count as one question."""
    monkeypatch.setattr(generation, "get_embedder",
                        lambda: lambda texts: [[1.0, 0.0] if "frying pan" in t else [0.0, 1.0]
                                               for t in texts])
    model.reply["value"] = answer([
        good("Which part of a frying pan should let heat through?"),
        good("Which frying pan part is best at passing heat?"),
    ])
    body = run(client, session, heat).json()
    assert body["produced"] == 1
    assert "near-copy" in body["dropped"][0]["problems"][0]


def test_each_option_keeps_its_own_misconception_when_the_key_is_not_first(
    client, session, heat, model  # noqa: F811
):
    """The live run of 20 October: with a separate list the model put the
    empty entry first whatever the key's position. Paired, it cannot."""
    model.reply["value"] = answer([good("Which of these lets heat through slowest?", key=2)])
    assert run(client, session, heat).json()["produced"] == 1
    saved = drafts(session)[0]
    # Order is shuffled on saving; what must survive is each pairing.
    assert saved.options[saved.correct_option] == "Plastic"
    paired = dict(zip(saved.options, saved.misconceptions, strict=True))
    assert paired == {"Copper": WRONG[0], "Wood": WRONG[1], "Plastic": None,
                      "Cloth": WRONG[2]}


def test_shuffling_moves_the_key_and_keeps_every_pairing():
    """Across many seeds the key lands in every position, and an option
    never loses its own misconception."""
    import random

    texts = ["Copper", "Wood", "Plastic", "Cloth"]
    mis = ["", "thinks wood", "thinks plastic", "thinks cloth"]
    positions = set()
    for seed in range(40):
        t, m, key = shuffle_options(texts, mis, 0, random.Random(seed))
        positions.add(key)
        assert t[key] == "Copper"
        assert dict(zip(t, m, strict=True)) == dict(zip(texts, mis, strict=True))
    assert positions == {0, 1, 2, 3}


# --- failures --------------------------------------------------------------
def test_a_cut_off_answer_fails_and_saves_nothing(client, session, heat, model):  # noqa: F811
    model.reply["value"] = answer([good()], stop_reason="max_tokens")
    body = run(client, session, heat).json()
    assert body["status"] == "failed" and "cut off" in body["error"]
    assert drafts(session) == []


def test_an_answer_that_is_not_json_fails(client, session, heat, model):  # noqa: F811
    model.reply["value"] = answer([], raw="Here are your questions: 1. ...")
    body = run(client, session, heat).json()
    assert body["status"] == "failed" and "structured list" in body["error"]


def test_a_missing_api_key_is_said_plainly(client, session, heat, model):  # noqa: F811
    model.reply["value"] = RuntimeError("ANTHROPIC_API_KEY is not set, so nothing can be "
                                        "generated.")
    body = run(client, session, heat).json()
    assert body["status"] == "failed" and "ANTHROPIC_API_KEY" in body["error"]


# --- limits and scope ------------------------------------------------------
def test_the_daily_cap_holds_and_failures_do_not_count(client, session, heat, model):  # noqa: F811
    model.reply["value"] = answer([], stop_reason="max_tokens")
    assert run(client, session, heat).json()["status"] == "failed"

    model.reply["value"] = answer([])
    for _ in range(generation.RUNS_PER_DAY):
        assert run(client, session, heat).json()["status"] == "ready"
    r = client.post(f"/api/strands/{heat.strand_id}/generate", headers=auth(teacher(session)))
    assert r.status_code == 429
    assert session.scalar(select(func.count()).select_from(GenerationRun)) == (
        generation.RUNS_PER_DAY + 1
    )


def test_a_second_request_while_one_runs_is_refused(client, session, heat, model):  # noqa: F811
    session.add(GenerationRun(strand_id=heat.strand_id, school_id=teacher(session).school_id,
                              requested=5, status="pending"))
    session.commit()
    r = client.post(f"/api/strands/{heat.strand_id}/generate", headers=auth(teacher(session)))
    assert r.status_code == 409


def test_a_strand_no_class_at_the_school_uses_is_not_found(client, session, model):  # noqa: F811
    other = Strand(name="Elsewhere", level="Upper Primary")
    session.add(other)
    session.commit()
    r = client.post(f"/api/strands/{other.strand_id}/generate", headers=auth(teacher(session)))
    assert r.status_code == 404


def test_a_strand_without_curriculum_cannot_be_written_for(client, session, model):  # noqa: F811
    # The fixture's strand has no catalogue key until the `heat` fixture sets one.
    strand = session.scalar(select(Strand))
    r = client.post(f"/api/strands/{strand.strand_id}/generate", headers=auth(teacher(session)))
    assert r.status_code == 409


def test_another_schools_run_is_not_found(client, session, heat, model):  # noqa: F811
    body = run(client, session, heat).json()
    rival = School(name="Rival", type="private")
    outsider = Teacher(name="R", email="r@x.y", password_hash="x", school=rival)
    session.add_all([rival, outsider])
    session.commit()
    r = client.get(f"/api/generation-runs/{body['run_id']}", headers=auth(outsider))
    assert r.status_code == 404


def test_the_day_turns_over_at_midnight_in_kenya():
    late_evening_utc = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)
    start = generation.start_of_today(late_evening_utc)
    assert (start.year, start.month, start.day, start.hour) == (2026, 10, 21, 0)
