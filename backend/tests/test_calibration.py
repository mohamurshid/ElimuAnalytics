"""
Calibration and flagging tests.

The two-consecutive-assessment rule is the one the Phase 1 skeleton did not
have, and it is the rule that decides whether a child enters an intervention
queue. It is tested here from both directions: that one low assessment is not
enough, and that a low estimate built on too little evidence never counts at all.
"""

from __future__ import annotations

import pytest
from app.calibration import (
    CONSECUTIVE_FOR_FLAG,
    assess_strand,
    calibrate_strand,
    open_flags,
)
from app.irt import MAX_ITEMS_PER_CALIBRATION
from app.models import AbilityScore, GapFlag, Item
from sqlalchemy import select

from .test_repository import session  # noqa: F401 - pytest fixture


def test_calibration_writes_parameters_back(session):  # noqa: F811
    before = session.scalars(select(Item)).all()
    assert all(i.difficulty_b is None for i in before)

    summary = calibrate_strand(session, session.strand_id)

    assert summary["items_calibrated"] == 12
    assert summary["students_in_calibration"] == 40
    after = session.scalars(select(Item)).all()
    assert all(i.difficulty_b is not None for i in after)
    assert all(i.discrimination_a is not None for i in after)


def test_calibration_reports_low_discrimination_items(session):  # noqa: F811
    """Chapter 3 excludes items below 0.3 discrimination from the active bank.
    The count must be reported even when it is zero, so the teacher knows the
    check ran."""
    summary = calibrate_strand(session, session.strand_id)
    assert "low_discrimination_count" in summary
    assert summary["low_discrimination_count"] == len(summary["low_discrimination_items"])


def test_batch_ceiling_is_enforced(session, monkeypatch):  # noqa: F811
    """Day 2. Calibration cost rises non-linearly with item count, so a strand
    larger than the batch ceiling must be refused rather than run for hours."""
    monkeypatch.setattr("app.calibration.MAX_ITEMS_PER_CALIBRATION", 5)
    with pytest.raises(ValueError, match="batch ceiling"):
        calibrate_strand(session, session.strand_id)
    assert MAX_ITEMS_PER_CALIBRATION == 300  # the real value is unchanged


def test_assessment_records_estimates_but_skips_low_evidence(session):  # noqa: F811
    result = assess_strand(session, session.strand_id)

    assert result["learners"] == 40
    # Otieno answered three items: no estimate is recorded at all.
    assert result["skipped_insufficient_evidence"] == 1
    assert result["estimates_recorded"] == 39

    scores = session.scalars(select(AbilityScore)).all()
    assert len(scores) == 39
    otieno = session.students[2].student_id
    assert all(s.student_id != otieno for s in scores)


def test_one_low_assessment_does_not_flag(session):  # noqa: F811
    """The design requires two consecutive. One is not enough, however low."""
    result = assess_strand(session, session.strand_id)
    assert result["new_flags"] == 0
    assert open_flags(session) == []


def test_two_consecutive_assessments_raise_a_flag(session):  # noqa: F811
    assess_strand(session, session.strand_id)
    result = assess_strand(session, session.strand_id)

    assert CONSECUTIVE_FOR_FLAG == 2
    assert result["new_flags"] > 0
    flags = open_flags(session)
    assert flags
    chebet = session.students[0].student_id
    assert any(f.student_id == chebet for f in flags)


def test_flags_are_not_duplicated_on_reassessment(session):  # noqa: F811
    assess_strand(session, session.strand_id)
    assess_strand(session, session.strand_id)
    first = len(open_flags(session))
    assess_strand(session, session.strand_id)
    assert len(open_flags(session)) == first


def test_a_learner_below_the_evidence_threshold_is_never_flagged(session):  # noqa: F811
    """Otieno has three responses. However many assessment cycles run, he must
    not enter the intervention queue on the strength of them."""
    otieno = session.students[2].student_id
    for _ in range(4):
        assess_strand(session, session.strand_id)
    assert session.scalar(
        select(GapFlag).where(GapFlag.student_id == otieno)
    ) is None
