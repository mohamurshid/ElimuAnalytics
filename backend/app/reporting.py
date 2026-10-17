"""
Generating a grounded intervention report for one learner in one strand.

This is where the pieces meet: diagnostics say how the learner is doing, the
failure pattern says what they got wrong, retrieval says which curriculum
applies, the prompt asks for a report, the model writes one, and the grounding
check decides whether it may leave the building.

WHAT THIS ENDPOINT REFUSES TO DO
--------------------------------
It refuses more often than it succeeds, and each refusal is deliberate.

  * No learning area on the strand -> 400. Retrieval filters on grade AND
    learning area before similarity, and that filter is the only reason
    retrieval works: 45.3% top-1 unfiltered against 100% filtered. Guessing
    the learning area would quietly produce a report grounded in the wrong
    subject's curriculum.
  * No ability estimate -> 409. The engine declines to estimate below five
    answered items; a report asserting a gap it cannot measure would be worse
    than no report. The message passed back is the engine's own.
  * No curriculum for that grade and learning area -> 409. Nothing to ground
    against. Grade 2 Kiswahili, for instance, extracted zero chunks because
    pdfminer cannot read that PDF's encryption dictionary.

A failure in generation itself - no API key, a provider that refuses - is NOT
one of these. Those were 503 and 502 while generation happened inside the
request; the row now outlives the request, so they are recorded on it as a
status and a sentence instead. `failure_text` is where that distinction
lives now, and it is the same distinction: what to fix, in words, rather
than FastAPI's generic "Internal Server Error".

SAVE, FLAG, REFUSE EXPORT
-------------------------
A report that fails its grounding check is still stored and still shown to the
teacher, marked - but `exportable` is false and it cannot be printed or sent
home. Discarding it would destroy the evidence of how often grounding fails,
which is precisely the data worth having.

A truncated or empty generation also sets `exportable` false regardless of its
verdict. A verdict on half a report is not a negative result, it is a
meaningless one, and a truncated report could easily contain one verified
citation and score GROUNDED while being unfit to read.

BILINGUAL IN ONE ROW
--------------------
Both languages are generated in one request and stored on one Report, because
that is what the row was designed for and what the measured bilingual cost
refers to. The verdict is the WORSE of the two and export requires BOTH to
pass: a report sent home is only as good as the half the parent can read.

The two calls run concurrently. Sequentially they took 32 to 38 seconds
measured end to end, and the development proxy in front of Next gives up at
about thirty: the work completed, the row was committed, and the reply had
nowhere to go - so a teacher saw an error for a report that exists and has
been paid for. They are independent calls and there was never a reason to
wait for the first before starting the second.

Everything downstream of the two calls is still done in `languages` order,
not completion order. With both in flight the faster one finishes first, and
keying any of it by position would file the Kiswahili report as English -
which is the same mistake that once priced the bilingual run from the wrong
list positions.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import grounding
from . import repository as repo
from .auth import current_teacher
from .db import get_session, get_session_factory
from .irt import ResponseMatrixError
from .models import Report, Strand, Student, Teacher
from .reports import LearnerFacts, build_prompt, generate
from .retrieval import retrieve

router = APIRouter(prefix="/api", tags=["reports"])

ENGLISH = "English"
KISWAHILI = "Kiswahili"
LANGUAGES = (ENGLISH, KISWAHILI)

# Worst first. Used to reduce two per-language verdicts to one.
VERDICT_RANK = {"FABRICATED": 0, "WEAK": 1, "GROUNDED": 2}

# A report's life. It is handed to the teacher as `pending` before a model has
# been called, because generation takes about half a minute and no request
# should be held open that long.
PENDING = "pending"
READY = "ready"
FAILED = "failed"


class ReportOut(BaseModel):
    report_id: str
    student_id: str
    strand_id: str | None
    learner: str
    content_en: str | None
    content_sw: str | None
    verdict: str | None
    exportable: bool
    status: str
    error: str | None
    duration_ms: int | None
    detail: str
    top_similarity: float | None
    chunk_source_rows: list[int] | None
    model: str | None
    effort: str | None
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    cost_usd: float | None
    grounding: dict | None
    generated_at: str | None


def split_strand_name(name: str) -> tuple[str, str]:
    """"3.0 Force and Energy / 3.3 Heat Transfer" -> the two halves.

    A Strand carries one `name`, but the prompt names the strand and the
    sub-strand separately because KICD's own documents do. Where the name
    carries no separator both fields get the whole thing, which is honest: the
    report then says what the database knows and no more.
    """
    if " / " in name:
        head, tail = name.split(" / ", 1)
        return head.strip(), tail.strip()
    return name, name


def worst_verdict(verdicts: list[str]) -> str | None:
    if not verdicts:
        return None
    return min(verdicts, key=lambda v: VERDICT_RANK.get(v, -1))


def provider_errors() -> tuple[type[BaseException], ...]:
    """The model provider's own exception classes, or none if it is absent.

    Imported on demand for the same reason `reports.py` imports the client on
    demand: this module has to be importable without the `anthropic` package,
    and the test suite never reaches the live API. An empty tuple in an
    `except` clause matches nothing, which is the correct behaviour when the
    package is not installed - there is then no provider call to fail.
    """
    try:
        from anthropic import APIError
    except ImportError:  # pragma: no cover - declared in requirements.txt
        return ()
    return (APIError,)


def provider_detail(exc: BaseException) -> str:
    """What the teacher is told when the provider refuses.

    The provider's own message is deliberately NOT forwarded. It can carry a
    request id, an organisation id or a billing hint, and this string is
    rendered in a browser and may be read over a teacher's shoulder. The full
    message is in the server log, where the person who can act on it already
    is.
    """
    status = getattr(exc, "status_code", None)
    named = type(exc).__name__ + (f", HTTP {status}" if status else "")
    return (
        f"The model provider did not answer ({named}), so no report was "
        f"generated and nothing was saved. Trying again is reasonable; the "
        f"server log carries the provider's own message."
    )


def detail_for(report: Report) -> str:
    """The sentence shown to the teacher, derived from the stored row.

    Derived rather than stored because one row now carries three outcomes in
    turn: pending, then ready or failed. Deriving also repairs a smaller
    fault - the list endpoint passed an empty detail, so a report that read
    clearly when it was generated lost its explanation on the next reload.
    """
    if report.status == PENDING:
        return (
            "Both languages are being generated. This takes about half a "
            "minute, and the page updates itself when it is done."
        )
    if report.status == FAILED:
        return report.error or "The report could not be generated."

    checks = report.grounding or {}
    # Read in LANGUAGES order rather than the JSON's, so the sentence cannot
    # change because a column type stopped preserving insertion order.
    unusable = [
        language
        for language in LANGUAGES
        if (checks.get(language) or {}).get("truncated")
        or (checks.get(language) or {}).get("empty")
    ]
    if unusable:
        return (
            f"The model returned a truncated or empty report in "
            f"{', '.join(unusable)}. It is saved for the record but cannot be "
            f"exported. Generating it again is the right next step."
        )
    if report.exportable:
        return (
            "Every citation in this report was verified against the retrieved "
            "KICD curriculum. It can be exported."
        )
    return (
        f"This report did not pass the grounding check ({report.verdict}). It "
        f"is saved and visible, but cannot be exported or sent home."
    )


def _out(report: Report, learner: str) -> ReportOut:
    return ReportOut(
        report_id=str(report.report_id),
        student_id=str(report.student_id),
        strand_id=str(report.strand_id) if report.strand_id else None,
        learner=learner,
        content_en=report.content_en,
        content_sw=report.content_sw,
        verdict=report.verdict,
        exportable=report.exportable,
        status=report.status,
        error=report.error,
        duration_ms=report.duration_ms,
        detail=detail_for(report),
        top_similarity=report.top_similarity,
        chunk_source_rows=report.chunk_source_rows,
        model=report.model,
        effort=report.effort,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        thinking_tokens=report.thinking_tokens,
        cost_usd=report.cost_usd,
        grounding=report.grounding,
        generated_at=report.generated_at.isoformat() if report.generated_at else None,
    )


def worker_session() -> Session:
    """A session of the background worker's own.

    It cannot use the request's: FastAPI closes that before a background task
    runs. Indirected through a function for the same reason the embedder and
    the model client are - the test suite runs on SQLite and has to be able
    to hand the worker the session the test is already holding.
    """
    return get_session_factory()()


def create_pending(session: Session, student: Student, strand: Strand) -> Report:
    """The row handed to the teacher before any model has been called.

    Committing first is what makes a timeout survivable. Until this existed, a
    generation that outlived the connection in front of it still finished,
    still cost money, and still wrote a row - while the teacher was shown a
    failure and clicked again, paying twice for a report they already had.
    """
    report = Report(
        student_id=student.student_id,
        strand_id=strand.strand_id,
        status=PENDING,
    )
    session.add(report)
    session.commit()
    return report


def failure_text(exc: BaseException) -> str:
    """What the teacher is told when generation fails.

    These were HTTP statuses while generation happened inside the request:
    503 for a server with no API key, 502 for a provider that refused.
    Asynchronously there is no response left to carry a status, so the
    distinction survives as the sentence stored on the row - which was always
    the part worth having. The provider's own message is still withheld; see
    provider_detail.
    """
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, provider_errors()):
        return provider_detail(exc)
    return (
        f"The report could not be generated: an unexpected "
        f"{type(exc).__name__} in the server. This is a fault to fix rather "
        f"than anything to do with this learner, and the server log has the "
        f"traceback."
    )


def fill_report(
    report_id: uuid.UUID,
    retrieved: list,
    *,
    session: Session | None = None,
) -> None:
    """Generate, ground and store. Records failure on the row; never raises.

    By the time this runs there may be no client listening, and an exception
    in a background task has nowhere to go: it would leave the row pending
    for ever and the teacher watching a spinner that never resolves. Here a
    failure is an outcome, written down.

    A row that is no longer pending is left alone. Filling it again would
    spend money to overwrite a finished report.
    """
    own = session is None
    session = session or worker_session()
    try:
        report = session.get(Report, report_id)
        if report is None or report.status != PENDING:
            return
        try:
            _generate_into(session, report, retrieved)
        except Exception as exc:
            session.rollback()
            report = session.get(Report, report_id)
            if report is not None:
                report.status = FAILED
                report.error = failure_text(exc)
                session.commit()
            print(f"report failed: {type(exc).__name__}: {exc}")
    finally:
        if own:
            session.close()


def _generate_into(
    session: Session,
    report: Report,
    retrieved: list,
    *,
    languages: tuple[str, ...] = LANGUAGES,
) -> None:
    """The work itself, written onto a row that already exists.

    Reads the learner and strand back from the row rather than taking them as
    arguments, because the caller that matters runs after the request has
    gone and cannot pass ORM objects across a closed session.
    """
    student = session.get(Student, report.student_id)
    strand = session.get(Strand, report.strand_id)
    if student is None or strand is None:
        raise ValueError("The learner or strand was removed before the report ran.")

    grade = student.classroom.grade if student.classroom else None
    if not grade:
        raise ValueError("The learner is not in a classroom, so the grade is unknown.")

    diagnosis = repo.diagnose_student(session, strand.strand_id, student.student_id)
    pattern = repo.learner_failure_pattern(
        session, student.student_id, strand.strand_id
    )
    flags = repo.consecutive_low_assessments(
        session, student.student_id, strand.strand_id
    )
    strand_name, sub_strand = split_strand_name(strand.name)

    facts = LearnerFacts(
        name=student.name,
        grade=grade,
        strand=strand_name,
        sub_strand=sub_strand,
        theta=round(float(diagnosis["theta"]), 2),
        tier=diagnosis["tier"],
        items_answered=diagnosis["answered"],
        consecutive_flags=flags,
    )

    chunk_texts = [r.syllabus_text for r in retrieved]
    context = "\n\n".join(chunk_texts)

    started = time.perf_counter()
    content: dict[str, str] = {}
    checks: dict[str, dict] = {}
    totals = {"input": 0, "output": 0, "thinking": 0, "cost": 0.0}
    unusable: list[str] = []
    model = effort = None

    # Submitted together, read back in a fixed order. `future.result()`
    # re-raises whatever the call raised, so a missing API key or a provider
    # error still reaches fill_report's handler unchanged - the cost is that a
    # failure in one language now wastes the other's spend, because both were
    # already in flight.
    with ThreadPoolExecutor(max_workers=len(languages)) as pool:
        pending = {
            language: pool.submit(
                generate,
                build_prompt(
                    facts, chunk_texts, language=language, failure_pattern=pattern
                ),
            )
            for language in languages
        }
        results = {
            language: future.result() for language, future in pending.items()
        }

    for language in languages:
        result = results[language]
        content[language] = result.text
        model, effort = result.model, result.effort

        check = grounding.check(result.text, context)
        # A verdict on half a report is meaningless rather than negative, so
        # the fact of truncation is recorded alongside it and export is
        # refused regardless of what the verdict says.
        check["truncated"] = result.truncated
        check["empty"] = result.empty
        checks[language] = check
        if result.truncated or result.empty:
            unusable.append(language)

        totals["input"] += result.input_tokens
        totals["output"] += result.output_tokens
        totals["thinking"] += result.thinking_tokens or 0
        totals["cost"] += result.cost_usd or 0.0

    elapsed = time.perf_counter() - started

    report.content_en = content.get(ENGLISH)
    report.content_sw = content.get(KISWAHILI)
    report.verdict = worst_verdict([c["verdict"] for c in checks.values()])
    report.exportable = bool(checks) and not unusable and all(
        c["exportable"] for c in checks.values()
    )
    report.grounding = checks
    report.top_similarity = retrieved[0].similarity if retrieved else None
    report.chunk_source_rows = [
        r.source_row for r in retrieved if r.source_row is not None
    ]
    report.model = model
    report.effort = effort
    report.input_tokens = totals["input"]
    report.output_tokens = totals["output"]
    report.thinking_tokens = totals["thinking"] or None
    report.cost_usd = round(totals["cost"], 8)
    report.duration_ms = int(elapsed * 1000)
    report.error = None
    report.status = READY
    session.commit()

    # Printed as well as stored: the wall clock turned out to matter as much
    # as the money, and a tail of this log is how we found that out.
    print(
        f"report: {elapsed:.1f}s, {len(languages)} languages, "
        f"{totals['output']} output tokens, ${round(totals['cost'], 4)}"
    )


@router.post(
    "/students/{student_id}/reports", response_model=ReportOut, status_code=201
)
def create_report(
    student_id: uuid.UUID,
    strand_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ReportOut:
    student = repo.student_in_school(session, student_id, teacher.school_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")

    strand = repo.get_strand(session, strand_id)
    if strand is None:
        raise HTTPException(status_code=404, detail="Strand not found")
    if not strand.learning_area:
        raise HTTPException(
            status_code=400,
            detail=(
                f'The strand "{strand.name}" has no KICD learning area set, so the '
                f"curriculum cannot be retrieved for it. Set one before generating "
                f"a report; guessing would ground the report in the wrong subject."
            ),
        )

    grade = student.classroom.grade if student.classroom else None
    if not grade:
        raise HTTPException(
            status_code=400,
            detail="The learner is not in a classroom, so the grade is unknown.",
        )

    try:
        diagnosis = repo.diagnose_student(session, strand_id, student_id)
    except ResponseMatrixError as exc:
        # Caught BEFORE ValueError, not after. ResponseMatrixError subclasses
        # ValueError, and the first matching clause wins, so the order this
        # was written in made this branch unreachable: a violated Phase 0 rule
        # - a server bug - was being reported as a 409 the teacher was
        # expected to act on.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if diagnosis["theta"] is None:
        raise HTTPException(status_code=409, detail=diagnosis["message"])

    retrieved = retrieve(
        session, strand.name, grade=grade, learning_area=strand.learning_area
    )
    if not retrieved:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No curriculum is loaded for {grade} {strand.learning_area}, so "
                f"there is nothing to ground a report in. Run `tasks ingest`, and "
                f"check that this grade and learning area were extracted."
            ),
        )

    report = create_pending(session, student, strand)
    # Still synchronous, and still answering 201. The pending row, the worker
    # and the derived detail are all new, and running them inline means the
    # tests written against the old code prove the new internals produce the
    # same report. Answering 202 and handing the work to a background task is
    # the next step, deliberately not mixed into this one.
    fill_report(report.report_id, retrieved, session=session)
    session.refresh(report)
    return _out(report, student.name)


@router.get("/students/{student_id}/reports", response_model=list[ReportOut])
def list_reports(
    student_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[ReportOut]:
    student = repo.student_in_school(session, student_id, teacher.school_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Learner not found")

    reports = session.scalars(
        select(Report)
        .where(Report.student_id == student_id)
        .order_by(Report.generated_at.desc())
    ).all()
    return [_out(r, student.name) for r in reports]
