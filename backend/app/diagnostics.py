"""
Read endpoints the teacher-facing interface needs.

The Phase 1 skeleton exposed `/api/learners` and `/api/diagnose/{id}`. Both
are demonstration shortcuts: they are unauthenticated, they filter to the three
named learners, and diagnose silently uses the first strand in the database.
They stay, unchanged, so the plain HTML page keeps working, and they are
replaced by the endpoints here. Phase 3 should call these.

Three things the interface needs that did not exist:

  * the strand list, which was only reachable inside `/api/health`
  * a learner's results for a **named** strand, scoped to the caller's school
  * the whole class against every strand in one request, because a heatmap of
    forty learners across six strands is otherwise 240 round trips

Every endpoint here is authenticated and school-scoped, and an out-of-scope
record answers 404 for the reason given in `classrooms.py`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .calibration import open_flags
from .db import get_session
from .irt import CONFIDENT_RESPONSES, MIN_RESPONSES, diagnose_all
from .item_status import DRAFT, MEASURED, REPORTED
from .models import Classroom, GapFlag, Item, Strand, Student, Teacher

router = APIRouter(prefix="/api", tags=["diagnostics"])

INSUFFICIENT = "insufficient_evidence"
PROVISIONAL = "provisional"
ESTIMATED = "estimated"


class StrandOut(BaseModel):
    strand_id: str
    name: str
    level: str
    # Approved questions: what a quiz can be given from and what counts.
    active_items: int
    calibrated_items: int
    # Waiting on a teacher (drafts) or a head teacher (reported).
    draft_items: int = 0
    reported_items: int = 0
    # Null for strands made before the catalogue existed.
    grade: str | None = None
    learning_area: str | None = None
    curriculum_key: str | None = None


class CellOut(BaseModel):
    strand_id: str
    strand: str
    theta: float | None
    tier: str | None
    answered: int
    status: str
    message: str


class LearnerDiagnosticsOut(BaseModel):
    student_id: str
    name: str
    is_active: bool
    cells: list[CellOut]


class HeatmapOut(BaseModel):
    class_id: str
    grade: str
    name: str
    strands: list[StrandOut]
    learners: list[LearnerDiagnosticsOut]
    minimum_responses: int
    confident_responses: int


def _status(cell: dict) -> str:
    """Three states, not two.

    "No estimate" is a result the interface must render deliberately rather
    than as an empty cell, because a blank reads as a rendering fault when it
    is in fact the system declining to guess.
    """
    if cell["theta"] is None:
        return INSUFFICIENT
    return ESTIMATED if cell["confident"] else PROVISIONAL


def strand_out(session: Session, strand: Strand) -> StrandOut:
    by_status = dict(
        session.execute(
            select(Item.status, func.count())
            .where(Item.strand_id == strand.strand_id)
            .group_by(Item.status)
        ).all()
    )
    calibrated = session.scalar(
        select(func.count())
        .select_from(Item)
        .where(
            Item.strand_id == strand.strand_id,
            Item.status.in_(MEASURED),
            Item.difficulty_b.is_not(None),
        )
    ) or 0
    return StrandOut(
        strand_id=str(strand.strand_id),
        name=strand.name,
        level=strand.level,
        active_items=int(sum(by_status.get(s, 0) for s in MEASURED)),
        calibrated_items=int(calibrated),
        draft_items=int(by_status.get(DRAFT, 0)),
        reported_items=int(by_status.get(REPORTED, 0)),
        grade=strand.grade,
        learning_area=strand.learning_area,
        curriculum_key=strand.curriculum_key,
    )


def _cells_for_class(
    session: Session, class_id: uuid.UUID, strands: list[Strand]
) -> tuple[list[Student], dict[uuid.UUID, list[CellOut]]]:
    """One calibration per strand for the whole class, never one per learner.

    This is the Phase 2 performance finding applied to a read path: calibration
    is a property of the strand, so a forty-learner heatmap costs one
    calibration per strand rather than forty.
    """
    learners = repo.classroom_students(session, class_id)
    by_student: dict[uuid.UUID, list[CellOut]] = {s.student_id: [] for s in learners}

    for strand in strands:
        matrix, item_ids, student_ids = repo.build_response_matrix(
            session, strand.strand_id, class_id
        )
        if not item_ids or not student_ids:
            continue
        results = diagnose_all(matrix, len(item_ids), len(student_ids))
        for idx, student_id in enumerate(student_ids):
            if student_id not in by_student:
                continue
            r = results[idx]
            by_student[student_id].append(
                CellOut(
                    strand_id=str(strand.strand_id),
                    strand=strand.name,
                    theta=r["theta"],
                    tier=r["tier"],
                    answered=r["answered"],
                    status=_status(r),
                    message=r["message"],
                )
            )
    return learners, by_student


@router.get("/strands", response_model=list[StrandOut])
def list_strands(
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[StrandOut]:
    """Strands some current class at the caller's school is assessed on.

    Strand rows are shared across schools, so the unscoped list would show
    every school's choices - harmless while there was one strand, noise
    with many.
    """
    return [strand_out(session, s) for s in repo.school_strands(session, teacher.school_id)]


@router.get("/students/{student_id}/diagnostics", response_model=LearnerDiagnosticsOut)
def learner_diagnostics(
    student_id: uuid.UUID,
    strand_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> LearnerDiagnosticsOut:
    """One learner across every strand, or one named strand.

    `strand_id` is explicit here. The Phase 1 endpoint used whichever strand
    happened to sort first, which is invisible with one strand and wrong with
    six.
    """
    student = repo.student_in_school(session, student_id, teacher.school_id)
    if student is None:
        raise HTTPException(status_code=404, detail="No such learner")

    if strand_id is not None:
        strand = repo.get_strand(session, strand_id)
        if strand is None:
            raise HTTPException(status_code=404, detail="No such strand")
        strands = [strand]
    else:
        strands = repo.class_strands(session, student.class_id)

    _, by_student = _cells_for_class(session, student.class_id, strands)
    return LearnerDiagnosticsOut(
        student_id=str(student.student_id),
        name=student.name,
        is_active=student.is_active,
        cells=by_student.get(student.student_id, []),
    )


@router.get("/classrooms/{class_id}/heatmap", response_model=HeatmapOut)
def classroom_heatmap(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> HeatmapOut:
    """Every learner against every strand the class is assessed on, in one
    request."""
    classroom = repo.classroom_in_school(session, class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="No such classroom")

    strands = repo.class_strands(session, class_id)
    learners, by_student = _cells_for_class(session, class_id, strands)

    return HeatmapOut(
        class_id=str(classroom.class_id),
        grade=classroom.grade,
        name=classroom.name,
        strands=[strand_out(session, s) for s in strands],
        learners=[
            LearnerDiagnosticsOut(
                student_id=str(s.student_id),
                name=s.name,
                is_active=s.is_active,
                cells=by_student.get(s.student_id, []),
            )
            for s in learners
        ],
        minimum_responses=MIN_RESPONSES,
        confident_responses=CONFIDENT_RESPONSES,
    )


class FlagOut(BaseModel):
    flag_id: str
    student_id: str
    learner: str
    class_id: str
    strand_id: str
    strand: str
    severity: str
    flagged_at: str | None


@router.get("/flags", response_model=list[FlagOut])
def flags(
    strand_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[FlagOut]:
    """The intervention queue, for the caller's school only.

    This endpoint previously returned every open flag in the database. With
    one school that was invisible; with two it is a disclosure of other
    schools' learners.
    """
    out: list[FlagOut] = []
    for f in open_flags(session, strand_id):
        student = repo.student_in_school(session, f.student_id, teacher.school_id)
        if student is None:
            continue  # another school's learner
        strand = session.get(Strand, f.strand_id)
        out.append(
            FlagOut(
                flag_id=str(f.flag_id),
                student_id=str(student.student_id),
                learner=student.name,
                class_id=str(student.class_id),
                strand_id=str(f.strand_id),
                strand=strand.name if strand else str(f.strand_id),
                severity=f.severity,
                flagged_at=f.flagged_at.isoformat() if f.flagged_at else None,
            )
        )
    return out


assert Classroom and GapFlag  # imported for the mapper registry
