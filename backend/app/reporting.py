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
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import grounding
from . import repository as repo
from .auth import current_teacher
from .db import get_session
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


class ReportOut(BaseModel):
    report_id: str
    student_id: str
    strand_id: str | None
    learner: str
    content_en: str | None
    content_sw: str | None
    verdict: str | None
    exportable: bool
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


def _out(report: Report, learner: str, detail: str) -> ReportOut:
    return ReportOut(
        report_id=str(report.report_id),
        student_id=str(report.student_id),
        strand_id=str(report.strand_id) if report.strand_id else None,
        learner=learner,
        content_en=report.content_en,
        content_sw=report.content_sw,
        verdict=report.verdict,
        exportable=report.exportable,
        detail=detail,
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


def compose_report(
    session: Session,
    student: Student,
    strand: Strand,
    grade: str,
    retrieved: list,
    *,
    languages: tuple[str, ...] = LANGUAGES,
) -> tuple[Report, str]:
    """Generate, ground and persist. Returns the row and a one-line summary.

    Separated from the endpoint so it can be tested without a
    `curriculum_chunk` table: pgvector has no SQLite equivalent, so the
    retrieval query cannot run in the test suite, but everything downstream of
    it can and does.
    """
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

    content: dict[str, str] = {}
    checks: dict[str, dict] = {}
    totals = {"input": 0, "output": 0, "thinking": 0, "cost": 0.0}
    unusable: list[str] = []
    model = effort = None

    for language in languages:
        prompt = build_prompt(
            facts, chunk_texts, language=language, failure_pattern=pattern
        )
        result = generate(prompt)
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

    verdict = worst_verdict([c["verdict"] for c in checks.values()])
    exportable = bool(checks) and not unusable and all(
        c["exportable"] for c in checks.values()
    )

    report = Report(
        student_id=student.student_id,
        strand_id=strand.strand_id,
        content_en=content.get(ENGLISH),
        content_sw=content.get(KISWAHILI),
        verdict=verdict,
        exportable=exportable,
        grounding=checks,
        top_similarity=retrieved[0].similarity if retrieved else None,
        chunk_source_rows=[r.source_row for r in retrieved if r.source_row is not None],
        model=model,
        effort=effort,
        input_tokens=totals["input"],
        output_tokens=totals["output"],
        thinking_tokens=totals["thinking"] or None,
        cost_usd=round(totals["cost"], 8),
    )
    session.add(report)
    session.commit()

    if unusable:
        detail = (
            f"The model returned a truncated or empty report in "
            f"{', '.join(unusable)}. It is saved for the record but cannot be "
            f"exported. Generating it again is the right next step."
        )
    elif exportable:
        detail = (
            "Every citation in this report was verified against the retrieved "
            "KICD curriculum. It can be exported."
        )
    else:
        detail = (
            f"This report did not pass the grounding check ({verdict}). It is "
            f"saved and visible, but cannot be exported or sent home."
        )
    return report, detail


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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ResponseMatrixError as exc:
        # A violated Phase 0 rule is a server bug, not a bad request.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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

    report, detail = compose_report(session, student, strand, grade, retrieved)
    return _out(report, student.name, detail)


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
    return [_out(r, student.name, "") for r in reports]
