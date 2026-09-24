"""
Data access. This module replaces `data.py` from the Phase 1 skeleton.

`data.py` was the seam where the database was always going to arrive, and this
is it arriving: the functions have the same shape, the callers do not change.

The response-matrix builder is the load-bearing part. Three Phase 0 rules are
enforced here because this is the only place a matrix is constructed:

  * ITEMS x STUDENTS, never the transpose (girth calibrates a transposed matrix
    silently and returns meaningless numbers)
  * integer 0/1, never boolean, even though the column is boolean
  * unanswered items are girth.INVALID_RESPONSE, never NaN
"""

from __future__ import annotations

import uuid

import numpy as np
from girth import INVALID_RESPONSE
from sqlalchemy import select
from sqlalchemy.orm import Session

from .irt import diagnose as irt_diagnose
from .models import AbilityScore, Classroom, Item, Response, Strand, Student


def list_strands(session: Session) -> list[Strand]:
    return list(session.scalars(select(Strand).order_by(Strand.name)))


def get_strand(session: Session, strand_id: uuid.UUID) -> Strand | None:
    return session.get(Strand, strand_id)


def list_students(session: Session, class_id: uuid.UUID | None = None) -> list[Student]:
    stmt = select(Student).order_by(Student.name)
    if class_id:
        stmt = stmt.where(Student.class_id == class_id)
    return list(session.scalars(stmt))


def list_classrooms(session: Session) -> list[Classroom]:
    return list(session.scalars(select(Classroom).order_by(Classroom.grade)))


def build_response_matrix(
    session: Session, strand_id: uuid.UUID, class_id: uuid.UUID | None = None
) -> tuple[np.ndarray, list[uuid.UUID], list[uuid.UUID]]:
    """Return (matrix, item_ids, student_ids) for one strand.

    Shape is (n_items, n_students). Unanswered cells are INVALID_RESPONSE.
    """
    # Deactivated items are excluded: they are withdrawn from the bank but
    # their responses are kept, so historical estimates remain reproducible.
    items = list(
        session.scalars(
            select(Item)
            .where(Item.strand_id == strand_id, Item.is_active.is_(True))
            .order_by(Item.item_id)
        )
    )
    student_stmt = select(Student).order_by(Student.student_id)
    if class_id:
        student_stmt = student_stmt.where(Student.class_id == class_id)
    students = list(session.scalars(student_stmt))

    item_ids = [i.item_id for i in items]
    student_ids = [s.student_id for s in students]
    item_pos = {iid: n for n, iid in enumerate(item_ids)}
    student_pos = {sid: n for n, sid in enumerate(student_ids)}

    # ITEMS x STUDENTS, prefilled with the sentinel rather than zero: an
    # unanswered item is not a wrong answer, and encoding it as one would bias
    # every ability estimate downward.
    matrix = np.full((len(items), len(students)), INVALID_RESPONSE, dtype=int)

    rows = session.execute(
        select(Response.item_id, Response.student_id, Response.correctness).where(
            Response.item_id.in_(item_ids)
        )
    ).all()
    for item_id, student_id, correct in rows:
        r, c = item_pos.get(item_id), student_pos.get(student_id)
        if r is None or c is None:
            continue
        matrix[r, c] = 1 if correct else 0  # boolean -> integer, deliberately

    return matrix, item_ids, student_ids


def diagnose_student(
    session: Session,
    strand_id: uuid.UUID,
    student_id: uuid.UUID,
    class_id: uuid.UUID | None = None,
) -> dict:
    """Calibrate the strand, estimate this learner's ability, apply the Day 3 rule."""
    matrix, item_ids, student_ids = build_response_matrix(session, strand_id, class_id)
    if student_id not in student_ids:
        raise ValueError("Student has no responses in this strand")
    idx = student_ids.index(student_id)

    result = irt_diagnose(matrix, len(item_ids), len(student_ids), idx)

    student = session.get(Student, student_id)
    strand = session.get(Strand, strand_id)
    return {
        "learner": student.name if student else str(student_id),
        "strand": strand.name if strand else str(strand_id),
        "items_in_strand": len(item_ids),
        "class_size": len(student_ids),
        **result,
    }


def consecutive_low_assessments(
    session: Session, student_id: uuid.UUID, strand_id: uuid.UUID, threshold: float = 0.0
) -> int:
    """How many of the most recent ability estimates fall below threshold.

    The design flags a learner only after TWO consecutive below-threshold
    assessments; the Phase 1 skeleton checked one. Estimates that did not meet
    the minimum-responses rule are ignored rather than counted, so a learner
    cannot be flagged on the strength of a noisy estimate.
    """
    scores = list(
        session.scalars(
            select(AbilityScore)
            .where(
                AbilityScore.student_id == student_id,
                AbilityScore.strand_id == strand_id,
            )
            .order_by(AbilityScore.assessed_at.desc())
        )
    )
    from .irt import CONFIDENT_RESPONSES

    run = 0
    for s in scores:
        if s.items_answered < CONFIDENT_RESPONSES:
            continue
        if s.theta < threshold:
            run += 1
        else:
            break
    return run
