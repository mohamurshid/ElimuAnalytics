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
    learner_failure_pattern,
)
from app.seed import NAMED, QUESTION_BANK, simulated_choices, simulated_responses
from girth import INVALID_RESPONSE
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

PORTABLE_TABLES = [
    Base.metadata.tables[n]
    for n in (
        "school", "teacher", "refresh_token", "classroom", "student", "strand",
        "item", "assessment_batch", "response", "ability_score",
        "gap_flag", "report",
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
        items = [
            Item(
                question_text=question,
                options=options,
                correct_option=key,
                strand=strand,
            )
            for question, options, key in QUESTION_BANK
        ]
        students = [
            Student(name=NAMED.get(i, f"Learner {i + 1:02d}"), classroom=classroom)
            for i in range(40)
        ]
        s.add_all([school, teacher, classroom, strand, *items, *students])
        s.flush()

        matrix = simulated_responses()
        choices = simulated_choices(matrix)
        s.add_all(
            Response(
                student_id=students[c].student_id,
                item_id=items[r].item_id,
                correctness=bool(matrix[r, c]),
                selected_option=int(choices[r, c]),
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


# --------------------------------------------------------------------------
# The item-level failure pattern, which the report prompt reads
# --------------------------------------------------------------------------
def test_simulated_choices_leaves_the_response_matrix_untouched(session):
    """The regression that justifies a separate generator.

    `simulated_responses` is pinned by the theta = -1.741 expectation. Drawing
    the distractor choices from the same stream would advance it and silently
    change every ability estimate in the demonstration classroom.
    """
    before = simulated_responses()
    simulated_choices(before)
    after = simulated_responses()
    assert np.array_equal(before, after)


def test_every_choice_agrees_with_the_correctness_it_came_from():
    matrix = simulated_responses()
    choices = simulated_choices(matrix)
    for r, (_q, _options, key) in enumerate(QUESTION_BANK):
        for c in range(matrix.shape[1]):
            if matrix[r, c] == INVALID_RESPONSE:
                assert choices[r, c] == INVALID_RESPONSE
                continue
            assert (choices[r, c] == key) == bool(matrix[r, c])


def test_the_pattern_names_what_was_chosen_and_what_was_correct(session):
    chebet = session.students[0].student_id
    pattern = learner_failure_pattern(session, chebet, session.strand_id)

    assert pattern["answered"] == 12
    assert pattern["failed_items"], "Chebet is at theta -1.8; she got items wrong"
    assert pattern["unreported_failures"] == 0

    options_by_question = {q: options for q, options, _k in QUESTION_BANK}
    for failed in pattern["failed_items"]:
        options = options_by_question[failed["question"]]
        assert failed["chose"] in options
        assert failed["correct"] in options
        assert failed["chose"] != failed["correct"]


def test_correct_answers_never_appear_as_failures(session):
    chebet = session.students[0].student_id
    pattern = learner_failure_pattern(session, chebet, session.strand_id)
    assert len(pattern["failed_items"]) == pattern["answered"] - pattern["correct"]


def test_a_hand_marked_wrong_answer_is_counted_but_not_described(session):
    """An item a teacher asked aloud has no chosen option to report.

    It must still count towards `answered`, because it is evidence about the
    learner, but it cannot be described - and `unreported_failures` says so
    rather than the gap being silent.
    """
    learner = Student(name="Hand Marked", class_id=session.students[0].class_id)
    session.add(learner)
    session.flush()

    item = session.get(Item, build_response_matrix(session, session.strand_id)[1][0])
    session.add(
        Response(
            student_id=learner.student_id,
            item_id=item.item_id,
            correctness=False,
            selected_option=None,
        )
    )
    session.commit()

    pattern = learner_failure_pattern(session, learner.student_id, session.strand_id)
    assert pattern["answered"] == 1
    assert pattern["failed_items"] == []
    assert pattern["unreported_failures"] == 1


def test_the_pattern_is_scoped_to_one_strand(session):
    other = Strand(name="3.2 Sound Energy", level="Upper Primary")
    session.add(other)
    session.commit()

    pattern = learner_failure_pattern(
        session, session.students[0].student_id, other.strand_id
    )
    assert pattern == {
        "answered": 0,
        "correct": 0,
        "failed_items": [],
        "unreported_failures": 0,
    }


def test_random_distractors_do_not_form_a_planted_pattern():
    """The integrity property behind the seeding choice.

    Distractors are drawn uniformly, so across the cohort the wrong answers to
    an item spread across its distractors rather than concentrating on one. If
    they concentrated, a report on seeded data would name a misconception that
    had been planted for it to find, and the demonstration would be showing
    the system succeeding at a rigged task.
    """
    matrix = simulated_responses()
    choices = simulated_choices(matrix)
    spread_seen = 0
    for r, (_q, _options, key) in enumerate(QUESTION_BANK):
        wrong = {
            int(choices[r, c])
            for c in range(matrix.shape[1])
            if matrix[r, c] == 0
        }
        assert key not in wrong
        if len(wrong) > 1:
            spread_seen += 1
    assert spread_seen >= len(QUESTION_BANK) - 2
