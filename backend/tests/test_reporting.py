"""
Report generation endpoint tests.

Every refusal this endpoint makes is tested, because the refusals are the
design. A system that cheerfully produces a report when it cannot measure the
learner, or cannot find the curriculum, or cannot tell which subject the strand
belongs to, is worse than one that declines.

The generator is always a stub and `retrieve` is always patched. The stub is
for the usual reason - a test that calls an API can fail for reasons unrelated
to the code. The patch is a necessity: `curriculum_chunk` cannot be created on
SQLite because pgvector has no SQLite equivalent, so the retrieval query cannot
run here at all. It is covered instead by `tasks check` against the real
database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.db import get_session
from app.main import app
from app.models import Report, School, Student, Teacher
from app.reporting import split_strand_name, worst_verdict
from app.reports import set_generator
from app.retrieval import Retrieved
from app.security import ROLE_SCHOOL_ADMIN, create_token, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture

PASSWORD = "correct-horse"

CHUNK_TEXT = (
    "STRAND: 3.0 Force and Energy. SUB-STRAND: 3.3 Heat transfer. "
    "SUGGESTED LEARNING EXPERIENCES: carry out experiments to identify good and "
    "poor conductors of heat. "
    "Project 1: Learners to make oven gloves using locally available materials"
)
GROUNDED_REPORT = (
    'I recommend the project: "Learners to make oven gloves using locally '
    'available materials." Run it in small supervised groups.'
)
FABRICATED_REPORT = (
    'I recommend "learners should build a parabolic solar oven from kitchen foil."'
)


def chunk(similarity: float = 0.32, source_row: int = 1416) -> Retrieved:
    return Retrieved(
        chunk_id=uuid.uuid4(),
        grade="Grade 5",
        learning_area="Science and Technology",
        strand="3.0 Force and Energy",
        sub_strand="3.3 Heat transfer",
        syllabus_text=CHUNK_TEXT,
        source_id="g5_sciencea_14",
        source_row=source_row,
        similarity=similarity,
    )


def response(text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="scratch"),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=900,
            output_tokens=400,
            output_tokens_details=SimpleNamespace(thinking_tokens=250),
        ),
    )


def by_language(english: str, kiswahili: str, *, stop_reason: str = "end_turn"):
    """A generator that answers differently depending on the prompt's language."""

    def generator(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        text = kiswahili if "Kiswahili sanifu" in prompt else english
        return response(text, stop_reason=stop_reason)

    return generator


@pytest.fixture(autouse=True)
def _stubbed(monkeypatch):
    set_generator(by_language(GROUNDED_REPORT, GROUNDED_REPORT))
    monkeypatch.setattr("app.reporting.retrieve", lambda *a, **k: [chunk()])
    yield
    set_generator(None)


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
def heat(session):  # noqa: F811
    """The seeded strand, with the learning area the endpoint requires."""
    from app.models import Strand

    strand = session.scalar(select(Strand))
    strand.learning_area = "Science and Technology"
    session.commit()
    return strand


def auth(t: Teacher) -> dict:
    return {"Authorization": f"Bearer {create_token(t.teacher_id, t.role, t.email)}"}


def chebet(session) -> Student:  # noqa: F811
    return session.scalar(select(Student).where(Student.name.like("Chebet%")))


def post(client, student, strand, head):
    return client.post(
        f"/api/students/{student.student_id}/reports",
        params={"strand_id": str(strand.strand_id)},
        headers=auth(head),
    )


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------
def test_one_request_produces_one_bilingual_report(client, head, heat, session):  # noqa: F811
    r = post(client, chebet(session), heat, head)
    assert r.status_code == 201
    body = r.json()

    assert body["content_en"] and body["content_sw"]
    assert body["verdict"] == "GROUNDED"
    assert body["exportable"] is True
    assert "can be exported" in body["detail"]
    assert session.scalar(select(Report)) is not None


def test_both_languages_are_actually_asked_for(client, head, heat, session):  # noqa: F811
    prompts: list[str] = []

    def spy(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return response(GROUNDED_REPORT)

    set_generator(spy)
    post(client, chebet(session), heat, head)

    assert len(prompts) == 2
    assert any("Use clear, professional English." in p for p in prompts)
    assert any("Kiswahili sanifu" in p for p in prompts)


def test_the_evidence_trail_is_persisted(client, head, heat, session):  # noqa: F811
    post(client, chebet(session), heat, head)
    report = session.scalar(select(Report))

    assert report.model == "claude-haiku-5-5"
    assert report.effort == "low"
    assert report.top_similarity == pytest.approx(0.32)
    assert report.chunk_source_rows == [1416]
    # Summed across both languages: 2 x (900 in, 400 out, 250 thinking).
    assert report.input_tokens == 1800
    assert report.output_tokens == 800
    assert report.thinking_tokens == 500
    assert report.cost_usd == pytest.approx(2 * (900 / 1e6 * 0.10 + 400 / 1e6 * 0.50))
    assert set(report.grounding) == {"English", "Kiswahili"}


# --------------------------------------------------------------------------
# The composite verdict
# --------------------------------------------------------------------------
def test_the_worse_of_the_two_languages_decides(client, head, heat, session):  # noqa: F811
    """A report sent home is only as good as the half the parent can read."""
    set_generator(by_language(GROUNDED_REPORT, FABRICATED_REPORT))
    r = post(client, chebet(session), heat, head)

    body = r.json()
    assert body["verdict"] == "FABRICATED"
    assert body["exportable"] is False
    assert "cannot be exported" in body["detail"]
    # Both halves are still stored - the failure is the evidence.
    assert body["content_en"] and body["content_sw"]


def test_a_truncated_report_cannot_be_exported_whatever_its_verdict(
    client, head, heat, session  # noqa: F811
):
    """A verdict on half a report is meaningless, not negative.

    This text contains a genuine verified citation, so the grounding check
    says GROUNDED. It is still unfit to read and must not leave the building.
    """
    set_generator(by_language(GROUNDED_REPORT, GROUNDED_REPORT, stop_reason="max_tokens"))
    r = post(client, chebet(session), heat, head)

    body = r.json()
    assert body["verdict"] == "GROUNDED"
    assert body["exportable"] is False
    assert "truncated or empty" in body["detail"]
    assert body["grounding"]["English"]["truncated"] is True


def test_worst_verdict_orders_the_three_outcomes():
    assert worst_verdict(["GROUNDED", "WEAK"]) == "WEAK"
    assert worst_verdict(["WEAK", "FABRICATED"]) == "FABRICATED"
    assert worst_verdict(["GROUNDED", "GROUNDED"]) == "GROUNDED"
    assert worst_verdict([]) is None


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------
def test_a_strand_with_no_learning_area_is_refused(client, head, session):  # noqa: F811
    from app.models import Strand

    strand = session.scalar(select(Strand))
    strand.learning_area = None
    session.commit()

    r = post(client, chebet(session), strand, head)
    assert r.status_code == 400
    assert "no KICD learning area" in r.json()["detail"]
    assert session.scalar(select(Report)) is None


def test_a_learner_below_the_evidence_threshold_is_refused(
    client, head, heat, session  # noqa: F811
):
    """Otieno answered three items. The engine declines to estimate; so does this.

    A report asserting a gap it cannot measure would be worse than no report.
    """
    otieno = session.scalar(select(Student).where(Student.name.like("Otieno%")))
    r = post(client, otieno, heat, head)

    assert r.status_code == 409
    # The engine's own wording is passed straight through, so the teacher is
    # told the rule rather than a generic refusal.
    assert r.json()["detail"] == (
        "3 item(s) answered. At least 5 are needed before an ability estimate "
        "means anything."
    )
    assert session.scalar(select(Report)) is None


def test_a_learner_who_has_answered_nothing_is_refused(
    client, head, heat, session  # noqa: F811
):
    """A learner enrolled but not yet assessed.

    This goes through the evidence-threshold path rather than the
    "no responses in this strand" ValueError, because build_response_matrix
    includes every learner in the strand's cohort - a new arrival is a column
    of unanswered items, not an absent row. The ValueError branch in the
    endpoint stays as a guard for the case where a learner is genuinely not in
    the matrix at all.
    """
    fresh = Student(name="New Arrival", class_id=chebet(session).class_id)
    session.add(fresh)
    session.commit()

    r = post(client, fresh, heat, head)
    assert r.status_code == 409
    assert "0 item(s) answered" in r.json()["detail"]
    assert session.scalar(select(Report)) is None


def test_no_curriculum_for_that_grade_is_refused(
    client, head, heat, session, monkeypatch  # noqa: F811
):
    """Grade 2 Kiswahili extracted zero chunks; this is what that looks like."""
    monkeypatch.setattr("app.reporting.retrieve", lambda *a, **k: [])
    r = post(client, chebet(session), heat, head)

    assert r.status_code == 409
    assert "nothing to ground a report in" in r.json()["detail"]
    assert session.scalar(select(Report)) is None


def test_an_unknown_strand_is_not_found(client, head, session):  # noqa: F811
    r = client.post(
        f"/api/students/{chebet(session).student_id}/reports",
        params={"strand_id": str(uuid.uuid4())},
        headers=auth(head),
    )
    assert r.status_code == 404


def test_a_learner_in_another_school_is_not_found(client, head, heat, session):  # noqa: F811
    """404, not 403, for the reason given in classrooms.py: a 403 confirms the
    record exists."""
    other = School(name="Other School", type="private")
    session.add(other)
    session.commit()
    head.school_id = other.school_id
    session.commit()

    r = post(client, chebet(session), heat, head)
    assert r.status_code == 404


def test_generating_a_report_requires_authentication(client, heat, session):  # noqa: F811
    r = client.post(
        f"/api/students/{chebet(session).student_id}/reports",
        params={"strand_id": str(heat.strand_id)},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------
def test_reports_are_listed_for_a_learner(client, head, heat, session):  # noqa: F811
    post(client, chebet(session), heat, head)
    post(client, chebet(session), heat, head)

    r = client.get(
        f"/api/students/{chebet(session).student_id}/reports", headers=auth(head)
    )
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_listing_is_school_scoped(client, head, heat, session):  # noqa: F811
    other = School(name="Other School", type="private")
    session.add(other)
    session.commit()
    head.school_id = other.school_id
    session.commit()

    r = client.get(
        f"/api/students/{chebet(session).student_id}/reports", headers=auth(head)
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def test_a_combined_strand_name_is_split_for_the_prompt():
    assert split_strand_name("3.0 Force and Energy / 3.3 Heat Transfer") == (
        "3.0 Force and Energy",
        "3.3 Heat Transfer",
    )


def test_a_strand_name_with_no_separator_fills_both_fields():
    # Honest rather than clever: the report says what the database knows.
    assert split_strand_name("3.3 Heat Transfer") == (
        "3.3 Heat Transfer",
        "3.3 Heat Transfer",
    )
