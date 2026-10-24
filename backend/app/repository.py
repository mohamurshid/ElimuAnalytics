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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .irt import diagnose as irt_diagnose
from .item_status import MEASURED
from .models import AbilityScore, Classroom, ClassStrand, Item, Response, Strand, Student


def list_strands(session: Session) -> list[Strand]:
    """Every strand in the database, across every school. Not what a screen
    should show - see class_strands and school_strands."""
    return list(session.scalars(select(Strand).order_by(Strand.name)))


def curriculum_order(strand: Strand) -> tuple:
    """Grade, learning area, then sub-strand number as numbers.

    Not by name: the seeded strand is called "3.0 Force and Energy / 3.3 Heat
    Transfer" and catalogue strands "Force and Energy / 3.2 Sound Energy", so
    alphabetical order put 3.3 before 3.2. And not by the key as a string,
    which puts "10.1" before "2.1".
    """
    number = (strand.curriculum_key or "").rsplit("|", 1)[-1]
    parts = tuple(int(p) for p in number.split(".") if p.isdigit())
    return (strand.grade or "", strand.learning_area or "", parts or (999,), strand.name)


def class_strands(session: Session, class_id: uuid.UUID) -> list[Strand]:
    """The strands this class is assessed on, in curriculum order."""
    strands = session.scalars(
        select(Strand)
        .join(ClassStrand, ClassStrand.strand_id == Strand.strand_id)
        .where(ClassStrand.class_id == class_id)
    )
    return sorted(strands, key=curriculum_order)


def school_strands(session: Session, school_id: uuid.UUID) -> list[Strand]:
    """Strands at least one current class in the school is assessed on."""
    strands = session.scalars(
        select(Strand)
        .join(ClassStrand, ClassStrand.strand_id == Strand.strand_id)
        .join(Classroom, Classroom.class_id == ClassStrand.class_id)
        .where(Classroom.school_id == school_id, Classroom.is_active.is_(True))
        .distinct()
    )
    return sorted(strands, key=curriculum_order)


def school_strand_classes(session: Session, school_id: uuid.UUID) -> dict:
    """strand_id -> the id of one current class at the school assessed on it
    (the lowest grade, then name, so the choice is stable)."""
    rows = session.execute(
        select(ClassStrand.strand_id, Classroom.class_id)
        .join(Classroom, Classroom.class_id == ClassStrand.class_id)
        .where(Classroom.school_id == school_id, Classroom.is_active.is_(True))
        .order_by(Classroom.grade, Classroom.name, Classroom.class_id)
    ).all()
    first: dict = {}
    for strand_id, class_id in rows:
        first.setdefault(strand_id, str(class_id))
    return first


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
    # Only questions that count (item_status.MEASURED). Retired, reported and
    # draft questions are left out, but their responses are kept, so a
    # question that is approved again counts again.
    items = list(
        session.scalars(
            select(Item)
            .where(Item.strand_id == strand_id, Item.status.in_(MEASURED))
            .order_by(Item.item_id)
        )
    )
    # Withdrawn learners leave the calibration pool for the same reason
    # deactivated items do: their past responses stay on record, but they no
    # longer contribute to estimates for the learners still in the class.
    student_stmt = select(Student).where(Student.is_active.is_(True)).order_by(
        Student.student_id
    )
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


def stored_parameters(session: Session, item_ids: list[uuid.UUID]) -> dict | None:
    """The saved difficulty and discrimination of these items, in this order,
    NaN where an item has not been calibrated. None if there are no items.

    The IRT engine decides whether they will do: an unanswered item without
    parameters is fine, an answered one means the strand is calibrated
    afresh (irt.diagnose_all).
    """
    if not item_ids:
        return None
    rows = {
        item_id: (b, a)
        for item_id, b, a in session.execute(
            select(Item.item_id, Item.difficulty_b, Item.discrimination_a).where(
                Item.item_id.in_(item_ids)
            )
        )
    }
    pairs = [rows.get(i) or (None, None) for i in item_ids]
    return {
        "difficulty": np.array([np.nan if b is None else b for b, _ in pairs], dtype=float),
        "discrimination": np.array([np.nan if a is None else a for _, a in pairs], dtype=float),
    }


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


# ---------------------------------------------------------------------------
# School-level scoping
#
# Every classroom and learner lookup goes through these. A teacher sees the
# classrooms and learners of their own school and nothing else.
#
# Out-of-scope records return None, and the API turns that into 404 rather
# than 403. 403 would confirm that a record exists and merely belongs to
# someone else, which is itself a disclosure: an attacker enumerating UUIDs
# learns which ones are real. 404 says only "not yours to know about".
# ---------------------------------------------------------------------------


def school_classrooms(
    session: Session, school_id: uuid.UUID, include_inactive: bool = False
) -> list[Classroom]:
    stmt = select(Classroom).where(Classroom.school_id == school_id)
    if not include_inactive:
        stmt = stmt.where(Classroom.is_active.is_(True))
    return list(session.scalars(stmt.order_by(Classroom.grade, Classroom.name)))


def classroom_in_school(
    session: Session, class_id: uuid.UUID, school_id: uuid.UUID
) -> Classroom | None:
    """The classroom, or None if it does not exist OR belongs to another school.

    The two cases are deliberately indistinguishable to the caller.
    """
    classroom = session.get(Classroom, class_id)
    if classroom is None or classroom.school_id != school_id:
        return None
    return classroom


def student_in_school(
    session: Session, student_id: uuid.UUID, school_id: uuid.UUID
) -> Student | None:
    student = session.get(Student, student_id)
    if student is None:
        return None
    classroom = session.get(Classroom, student.class_id)
    if classroom is None or classroom.school_id != school_id:
        return None
    return student


def classroom_students(
    session: Session, class_id: uuid.UUID, include_inactive: bool = False
) -> list[Student]:
    stmt = select(Student).where(Student.class_id == class_id)
    if not include_inactive:
        stmt = stmt.where(Student.is_active.is_(True))
    return list(session.scalars(stmt.order_by(Student.name)))


def learner_failure_pattern(
    session: Session, student_id: uuid.UUID, strand_id: uuid.UUID
) -> dict:
    """What this learner got wrong in this strand, and what they chose instead.

    The report prompt needs this. In the 14 October spike run both English
    conditions stopped and asked for it unprompted - "the item-level breakdown
    is not provided, so the failing outcome cannot be confirmed" - and the
    condition that supplied it turned "please review her scripts" into a named
    misconception. The data was already in the database; the prompt was
    withholding it.

    Only items that can actually be reported on are included. An item needs
    both `options` and `correct_option` to say what was chosen instead of what,
    and a response needs `selected_option` to say anything at all. Items a
    teacher asked aloud and marked by hand have neither, and they are counted
    in `answered` but cannot appear in `failed_items` - so a report built from
    hand-marked assessments correctly carries no failure pattern rather than a
    misleading partial one.

    `unreported_failures` makes that gap visible instead of silent: it is the
    number of wrong answers that exist but cannot be described.

    Only questions that count (item_status.MEASURED), the same set the
    learner's level is estimated from. Otherwise a reported question - one a
    teacher thinks has a wrong key - could be named in a report as the
    learner's misconception, and `answered` would disagree with the level
    printed beside it.
    """
    rows = session.execute(
        select(Response, Item)
        .join(Item, Item.item_id == Response.item_id)
        .where(
            Response.student_id == student_id,
            Item.strand_id == strand_id,
            Item.status.in_(MEASURED),
        )
        .order_by(Item.question_text)
    ).all()

    answered = len(rows)
    correct = sum(1 for response, _item in rows if response.correctness)

    failed_items: list[dict] = []
    unreported = 0
    for response, item in rows:
        if response.correctness:
            continue
        options = item.options or []
        chosen = response.selected_option
        key = item.correct_option
        if (
            chosen is None
            or key is None
            or not 0 <= chosen < len(options)
            or not 0 <= key < len(options)
        ):
            unreported += 1
            continue
        failed_items.append(
            {
                "item_id": item.item_id,
                "question": item.question_text,
                "chose": options[chosen],
                "correct": options[key],
            }
        )

    return {
        "answered": answered,
        "correct": correct,
        "failed_items": failed_items,
        "unreported_failures": unreported,
    }


def student_response_count(session: Session, student_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Response)
            .where(Response.student_id == student_id)
        )
        or 0
    )


def classroom_response_count(session: Session, class_id: uuid.UUID) -> int:
    """Responses recorded by any learner in this classroom, active or not."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(Response)
            .join(Student, Student.student_id == Response.student_id)
            .where(Student.class_id == class_id)
        )
        or 0
    )
