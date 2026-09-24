"""
Phase 2 persistence tests.

The point of these is not that the ORM works - it is that moving from an
in-memory array to a database did not change the answer. The Phase 1 skeleton
estimated Chebet at theta = -1.741 from twelve items. If the database path
produces a different number, the database layer has introduced an error.

They run against SQLite, so no Docker or Postgres is needed to run the suite.
The curriculum_chunk table is excluded because pgvector has no SQLite
equivalent; it is exercised in Phase 5 against the real database.
"""

from __future__ import annotations

import numpy as np
import pytest
from app.models import (
    AbilityScore,
    Base,
    Classroom,
    Item,
    Response,
    School,
    Strand,
    Student,
    Teacher,
)
from app.repository import (
    build_response_matrix,
    consecutive_low_assessments,
    diagnose_student,
)
from app.seed import NAMED, QUESTIONS, simulated_responses
from girth import INVALID_RESPONSE
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

PORTABLE_TABLES = [
    Base.metadata.tables[n]
    for n in (
        "school", "teacher", "classroom", "student", "strand",
        "item", "response", "ability_score", "gap_flag", "report",
    )
]


@pytest.fixture
def session() -> Session:
    # StaticPool + check_same_thread=False: FastAPI's TestClient runs the app in
    # its own thread, and a default in-memory SQLite connection is bound to the
    # thread that created it.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=PORTABLE_TABLES)
    with Session(engine) as s:
        school = School(name="Test School", type="public")
        teacher = Teacher(name="T", email="t@x.y", password_hash="x", school=school)
        classroom = Classroom(grade="Grade 5", school=school, teacher=teacher)
        strand = Strand(name="3.3 Heat Transfer", level="Upper Primary")
        items = [Item(question_text=q, strand=strand) for q in QUESTIONS]
        students = [
            Student(name=NAMED.get(i, f"Learner {i + 1:02d}"), classroom=classroom)
            for i in range(40)
        ]
        s.add_all([school, teacher, classroom, strand, *items, *students])
        s.flush()

        matrix = simulated_responses()
        s.add_all(
            Response(
                student_id=students[c].student_id,
                item_id=items[r].item_id,
                correctness=bool(matrix[r, c]),
            )
            for r in range(matrix.shape[0])
            for c in range(matrix.shape[1])
            if matrix[r, c] != INVALID_RESPONSE
        )
        s.commit()
        s.strand_id = strand.strand_id  # type: ignore[attr-defined]
        s.students = students  # type: ignore[attr-defined]
        yield s


def test_matrix_is_items_by_students(session):
    """Day 1. The database must hand girth the orientation it requires."""
    matrix, item_ids, student_ids = build_response_matrix(session, session.strand_id)
    assert matrix.shape == (len(item_ids), len(student_ids))
    assert matrix.shape == (12, 40)


def test_matrix_is_integer_not_boolean(session):
    """Day 1. The column is boolean; girth needs integers."""
    matrix, _, _ = build_response_matrix(session, session.strand_id)
    assert np.issubdtype(matrix.dtype, np.integer)
    assert matrix.dtype != bool


def test_unanswered_items_use_sentinel_not_zero(session):
    """Day 1 and Day 3. An unanswered item is not a wrong answer. Encoding it
    as zero would bias every ability estimate downward."""
    matrix, _, student_ids = build_response_matrix(session, session.strand_id)
    otieno = student_ids.index(session.students[2].student_id)
    column = matrix[:, otieno]
    assert (column == INVALID_RESPONSE).sum() == 9
    assert np.count_nonzero(column != INVALID_RESPONSE) == 3


def test_database_reproduces_the_skeleton_estimate(session):
    """The number must not move when persistence is introduced."""
    result = diagnose_student(session, session.strand_id, session.students[0].student_id)
    assert result["learner"] == "Chebet K."
    assert result["answered"] == 12
    assert result["theta"] == pytest.approx(-1.741, abs=0.01)
    assert result["tier"] == "Below expectation"
    assert result["flaggable"] is True


def test_minimum_responses_rule_survives_the_database(session):
    """Day 3. Otieno answered three items: no theta, no tier, not flaggable."""
    result = diagnose_student(session, session.strand_id, session.students[2].student_id)
    assert result["answered"] == 3
    assert result["theta"] is None
    assert result["tier"] is None
    assert result["flaggable"] is False


def test_consecutive_flagging_needs_two_assessments(session):
    """The design flags after two consecutive below-threshold assessments.
    The Phase 1 skeleton checked one."""
    sid = session.students[0].student_id
    strand = session.strand_id
    assert consecutive_low_assessments(session, sid, strand) == 0

    session.add(AbilityScore(student_id=sid, strand_id=strand, theta=-1.5,
                             items_answered=12))
    session.commit()
    assert consecutive_low_assessments(session, sid, strand) == 1

    session.add(AbilityScore(student_id=sid, strand_id=strand, theta=-1.2,
                             items_answered=12))
    session.commit()
    assert consecutive_low_assessments(session, sid, strand) == 2


def test_low_evidence_estimates_do_not_count_towards_flagging(session):
    """An estimate below the minimum-responses threshold is noise and must not
    contribute to a flag, however low it looks."""
    sid = session.students[1].student_id
    strand = session.strand_id
    session.add(AbilityScore(student_id=sid, strand_id=strand, theta=-3.0,
                             items_answered=2))
    session.commit()
    assert consecutive_low_assessments(session, sid, strand) == 0
