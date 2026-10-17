"""
Report generation endpoint tests.

Every refusal this endpoint makes is tested, because the refusals are the
design. A system that cheerfully produces a report when it cannot measure the
learner, or cannot find the curriculum, or cannot tell which subject the strand
belongs to, is worse than one that declines.

Generation is asynchronous, so a POST answers 202 with a `pending` row and
the response is serialised before the background task runs. Every assertion
about content, verdict, tokens or cost therefore belongs to the row read back
afterwards - `generated()` does both steps - and not to the POST's own body.
`TestClient` runs background tasks before handing the response over, so none
of this needs sleeping.

The generator is always a stub and `retrieve` is always patched. The stub is
for the usual reason - a test that calls an API can fail for reasons unrelated
to the code. The patch is a necessity: `curriculum_chunk` cannot be created on
SQLite because pgvector has no SQLite equivalent, so the retrieval query cannot
run here at all. It is covered instead by `tasks check` against the real
database.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.db import get_session
from app.irt import ResponseMatrixError
from app.main import app
from app.models import Report, School, Student, Teacher
from app.reporting import (
    FAILED,
    PENDING,
    READY,
    create_pending,
    detail_for,
    fill_report,
    is_stale,
    split_strand_name,
    worst_verdict,
)
from app.reports import set_generator
from app.retrieval import Retrieved
from app.security import ROLE_SCHOOL_ADMIN, create_token, hash_password
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

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
def client(session, monkeypatch):  # noqa: F811
    app.dependency_overrides[get_session] = lambda: session
    # The worker opens its own session, because FastAPI closes the request's
    # before a background task runs. Here it gets a second session on the
    # same in-memory database rather than the test's own, so that closing it
    # when the task finishes cannot pull the connection out from under the
    # assertions that follow.
    monkeypatch.setattr(
        "app.reporting.worker_session", lambda: SASession(session.get_bind())
    )
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


def fetch(client, student, report_id, head):
    return client.get(
        f"/api/students/{student.student_id}/reports/{report_id}",
        headers=auth(head),
    )


def generated(client, student, strand, head):
    """Ask for a report, then read back the finished row.

    The POST answers 202 with a pending row and nothing in it. Asserting
    content against that body would be asserting against the wrong moment -
    and would quietly keep passing if the worker never ran at all.
    """
    created = post(client, student, strand, head)
    assert created.status_code == 202
    assert created.json()["status"] == PENDING
    assert created.json()["content_en"] is None

    fetched = fetch(client, student, created.json()["report_id"], head)
    assert fetched.status_code == 200
    return fetched


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------
def test_one_request_produces_one_bilingual_report(client, head, heat, session):  # noqa: F811
    body = generated(client, chebet(session), heat, head).json()

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
    # Written by the worker's session, so this one has to look again.
    session.expire_all()
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
    body = generated(client, chebet(session), heat, head).json()
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
    body = generated(client, chebet(session), heat, head).json()
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
# --------------------------------------------------------------------------
# Failures that are nobody's fault
#
# These were HTTP statuses - 503 for a server with no API key, 502 for a
# provider that refused - while generation happened inside the request. The
# row now outlives the request, so a failure is recorded on it instead: the
# teacher still gets the sentence, and a report that failed is visible rather
# than silently absent. What must never happen is the row staying `pending`,
# because a spinner that never resolves is the one outcome a teacher cannot
# interpret.
# --------------------------------------------------------------------------
def raising(exc: BaseException):
    """A generator that fails the way the live client fails."""

    def generator(**kwargs):
        raise exc

    return generator


def connection_error():
    """A real `anthropic` exception instance, not a stand-in.

    Constructed from the installed class because the code catches the
    provider's own hierarchy: a home-made exception would pass this test
    while the real class went uncaught in production, which is the exact
    failure these tests exist to prevent.
    """
    import httpx
    from anthropic import APIConnectionError

    return APIConnectionError(
        message="workspace-id-and-billing-hint-live-in-here",
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def test_a_missing_api_key_is_explained_rather_than_crashing(
    client, head, heat, session  # noqa: F811
):
    set_generator(
        raising(
            RuntimeError("ANTHROPIC_API_KEY is not set, so no report can be generated.")
        )
    )
    body = generated(client, chebet(session), heat, head).json()

    assert body["status"] == FAILED
    # The client's own sentence, kept: it names the variable to set.
    assert "ANTHROPIC_API_KEY is not set" in body["error"]
    assert body["detail"] == body["error"]


def test_a_provider_failure_is_recorded_on_the_row(client, head, heat, session):  # noqa: F811
    set_generator(raising(connection_error()))
    body = generated(client, chebet(session), heat, head).json()

    assert body["status"] == FAILED
    assert "APIConnectionError" in body["error"]


def test_the_providers_own_message_is_not_shown_in_the_browser(
    client, head, heat, session  # noqa: F811
):
    set_generator(raising(connection_error()))
    body = generated(client, chebet(session), heat, head).json()

    assert "workspace-id-and-billing-hint" not in body["error"]
    assert "workspace-id-and-billing-hint" not in body["detail"]


def test_a_failed_generation_is_kept_rather_than_lost(client, head, heat, session):  # noqa: F811
    """The orphan is the point: a teacher must be able to see what happened.

    While generation lived inside the request a failure saved nothing, which
    was defensible then. Now the row is created first, so discarding it would
    mean deleting the only record that the attempt was made and paid for.
    """
    set_generator(raising(connection_error()))
    post(client, chebet(session), heat, head)
    session.expire_all()

    report = session.scalar(select(Report))
    assert report.status == FAILED
    assert report.content_en is None
    assert report.exportable is False


def test_a_failure_never_leaves_the_row_pending(client, head, heat, session):  # noqa: F811
    """A spinner that never resolves is the one outcome a teacher cannot read."""
    set_generator(raising(RuntimeError("boom")))
    post(client, chebet(session), heat, head)
    session.expire_all()

    assert session.scalar(select(Report)).status != PENDING


def test_a_violated_matrix_rule_is_a_server_bug_not_a_conflict(
    client, head, heat, session, monkeypatch  # noqa: F811
):
    """ResponseMatrixError subclasses ValueError, so clause order decides this.

    Written after finding that the broader `except ValueError` came first and
    made the 500 branch unreachable: a violated Phase 0 rule was answered with
    a 409, which tells a teacher to fix something only the code can fix.
    """

    def boom(*args, **kwargs):
        raise ResponseMatrixError("INVALID_RESPONSE reached the response matrix")

    monkeypatch.setattr("app.reporting.repo.diagnose_student", boom)
    r = post(client, chebet(session), heat, head)
    assert r.status_code == 500
    assert "INVALID_RESPONSE" in r.json()["detail"]


# --------------------------------------------------------------------------
# Concurrency
#
# The two calls were sequential, which put the request at 32-38 seconds and
# over the proxy's limit: the report was generated and committed, and the
# teacher was shown a failure for work they had already paid for.
# --------------------------------------------------------------------------
def test_the_two_languages_are_generated_concurrently(client, head, heat, session):  # noqa: F811
    """Sequential generation cannot pass this: the barrier would never fill.

    A barrier of two means each call blocks until the other has also started.
    One-at-a-time, the first wait times out, `BrokenBarrierError` propagates,
    and the request fails - so a green test here is positive evidence of
    overlap rather than an absence of evidence against it.
    """
    barrier = threading.Barrier(2, timeout=10)

    def generator(**kwargs):
        barrier.wait()
        return response(GROUNDED_REPORT)

    set_generator(generator)
    assert post(client, chebet(session), heat, head).status_code == 202


def test_completion_order_does_not_decide_which_language_is_stored(
    client, head, heat, session  # noqa: F811
):
    """English deliberately answers last, and must still be stored as English."""

    def generator(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Kiswahili sanifu" in prompt:
            return response("KISWAHILI BODY")
        time.sleep(0.2)
        return response("ENGLISH BODY")

    set_generator(generator)
    body = generated(client, chebet(session), heat, head).json()

    assert body["content_en"] == "ENGLISH BODY"
    assert body["content_sw"] == "KISWAHILI BODY"


# --------------------------------------------------------------------------
# The row's three states
# --------------------------------------------------------------------------
def test_a_finished_report_is_ready_and_timed(client, head, heat, session):  # noqa: F811
    body = generated(client, chebet(session), heat, head).json()

    assert body["status"] == READY
    assert body["duration_ms"] is not None and body["duration_ms"] >= 0
    assert body["error"] is None


def test_a_report_that_is_already_finished_is_not_generated_again(
    client, head, heat, session  # noqa: F811
):
    """Filling a finished row would spend money to overwrite a good report."""
    calls: list[str] = []

    def spy(**kwargs):
        calls.append(kwargs["messages"][0]["content"])
        return response(GROUNDED_REPORT)

    set_generator(spy)
    body = generated(client, chebet(session), heat, head).json()
    assert len(calls) == 2

    fill_report(uuid.UUID(body["report_id"]), [chunk()], session=session)

    assert len(calls) == 2


def test_the_pending_sentence_says_what_is_happening():
    """Derived, not stored: one row carries all three outcomes in turn."""
    assert "being generated" in detail_for(Report(status=PENDING))


def test_the_failed_sentence_is_the_stored_error():
    report = Report(status=FAILED, error="The provider did not answer.")
    assert detail_for(report) == "The provider did not answer."


def test_a_failed_row_with_no_error_still_says_something():
    assert detail_for(Report(status=FAILED)) != ""


# --------------------------------------------------------------------------
# Asking twice
#
# The page disables its button while a generation runs, but a second tab does
# not know that, and every report costs real money. This is the half of that
# guard the browser cannot provide.
# --------------------------------------------------------------------------
def test_a_second_request_while_one_is_pending_is_refused(
    client, head, heat, session  # noqa: F811
):
    learner = chebet(session)
    create_pending(session, learner, heat)

    r = post(client, learner, heat, head)

    assert r.status_code == 409
    assert "already being generated" in r.json()["detail"]


def test_a_stale_pending_row_does_not_block_a_new_request(
    client, head, heat, session  # noqa: F811
):
    """A worker that died must not lock the strand out for ever.

    This is the failure mode the five-minute rule exists for: a reload, a
    killed process or a closed laptop leaves a row pending, and without this
    the teacher could never ask for that report again.
    """
    learner = chebet(session)
    abandoned = create_pending(session, learner, heat)
    abandoned.generated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.commit()

    assert post(client, learner, heat, head).status_code == 202


def test_staleness_is_measured_against_five_minutes():
    recent = Report(status=PENDING, generated_at=datetime.now(timezone.utc))
    old = Report(
        status=PENDING,
        generated_at=datetime.now(timezone.utc) - timedelta(minutes=6),
    )

    assert is_stale(recent) is False
    assert is_stale(old) is True


def test_a_naive_timestamp_is_not_a_crash():
    """SQLite returns this column naive and PostgreSQL returns it aware.

    Comparing the two raises, so without the repair the rule would work in
    one environment and fail in the other.
    """
    # A fixed date in the past, so the answer is the same whatever the
    # machine's timezone: a naive "now" would read as stale on a machine
    # behind UTC and fresh on one ahead of it, and the test would be about
    # the clock rather than the code.
    naive = Report(status=PENDING, generated_at=datetime(2026, 1, 1, 12, 0))
    assert is_stale(naive) is True


def test_a_finished_report_is_never_stale():
    assert is_stale(Report(status=READY)) is False
    assert is_stale(Report(status=FAILED)) is False


# --------------------------------------------------------------------------
# Reading one report
# --------------------------------------------------------------------------
def test_one_report_can_be_fetched_on_its_own(client, head, heat, session):  # noqa: F811
    learner = chebet(session)
    created = post(client, learner, heat, head).json()

    body = fetch(client, learner, created["report_id"], head).json()

    assert body["report_id"] == created["report_id"]
    assert body["status"] == READY


def test_another_learners_report_is_not_found(client, head, heat, session):  # noqa: F811
    """Not "forbidden": whether it exists is not this teacher's business."""
    learner = chebet(session)
    created = post(client, learner, heat, head).json()
    other = session.scalars(
        select(Student).where(Student.student_id != learner.student_id)
    ).first()

    r = fetch(client, other, created["report_id"], head)

    assert r.status_code == 404


def test_an_unknown_report_is_not_found(client, head, heat, session):  # noqa: F811
    r = fetch(client, chebet(session), uuid.uuid4(), head)
    assert r.status_code == 404
