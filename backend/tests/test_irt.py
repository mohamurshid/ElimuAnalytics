"""
Regression tests for the Phase 0 spike findings.

These are not tests of girth. They are tests that this codebase cannot
reintroduce the four mistakes the spike found, three of which produce wrong
numbers rather than errors.

    pytest -q
"""

import numpy as np
import pytest
from girth import INVALID_RESPONSE

from app import data
from app.irt import (
    MIN_RESPONSES,
    ResponseMatrixError,
    diagnose,
    responses_answered,
    tier_for,
    validate_matrix,
)

N_ITEMS, N_STUDENTS = data.N_ITEMS, data.N_STUDENTS


def test_matrix_is_items_by_students():
    """Day 1. A transposed matrix must be rejected, not quietly calibrated."""
    good = data.response_matrix()
    assert good.shape == (N_ITEMS, N_STUDENTS)
    with pytest.raises(ResponseMatrixError, match="ITEMS x STUDENTS"):
        validate_matrix(good.T, N_ITEMS, N_STUDENTS)


def test_boolean_responses_rejected():
    """Day 1. Booleans cause internal girth errors; catch them at the door."""
    with pytest.raises(ResponseMatrixError, match="boolean"):
        validate_matrix(
            np.ones((N_ITEMS, N_STUDENTS), dtype=bool), N_ITEMS, N_STUDENTS
        )


def test_nan_rejected_in_favour_of_invalid_response():
    """Day 1. Missing data is INVALID_RESPONSE, never NaN."""
    m = data.response_matrix().astype(float)
    m[0, 0] = np.nan
    with pytest.raises(ResponseMatrixError, match="NaN"):
        validate_matrix(m, N_ITEMS, N_STUDENTS)


def test_invalid_response_is_accepted_and_not_counted():
    """INVALID_RESPONSE passes validation but does not count as an answer."""
    m = data.response_matrix().copy()
    m[0, 5] = INVALID_RESPONSE
    validate_matrix(m, N_ITEMS, N_STUDENTS)
    assert responses_answered(m, 5) == N_ITEMS - 1


def test_no_theta_below_minimum_responses():
    """Day 3. Learner 2 answered 3 items. No theta, no tier, not flaggable."""
    result = diagnose(data.response_matrix(), N_ITEMS, N_STUDENTS, 2)
    assert result["answered"] < MIN_RESPONSES
    assert result["theta"] is None
    assert result["tier"] is None
    assert result["flaggable"] is False


def test_theta_is_produced_above_minimum():
    result = diagnose(data.response_matrix(), N_ITEMS, N_STUDENTS, 0)
    assert result["answered"] >= MIN_RESPONSES
    assert isinstance(result["theta"], float)
    assert result["tier"] in {
        "Exceeds expectation",
        "Meets expectation",
        "Approaches expectation",
        "Below expectation",
    }


def test_ability_ordering_is_sane():
    """A learner who answered everything correctly must not score below one
    who answered everything wrongly. Catches sign and orientation errors that
    validation alone cannot."""
    m = data.response_matrix().copy()
    m[:, 10] = 1
    m[:, 11] = 0
    strong = diagnose(m, N_ITEMS, N_STUDENTS, 10)
    weak = diagnose(m, N_ITEMS, N_STUDENTS, 11)
    assert strong["theta"] > weak["theta"]


def test_tiers_use_kicd_wording():
    """Day 4. The four tier names are KICD's own, not invented."""
    assert tier_for(2.0) == "Exceeds expectation"
    assert tier_for(0.5) == "Meets expectation"
    assert tier_for(-0.5) == "Approaches expectation"
    assert tier_for(-1.8) == "Below expectation"


def test_batch_size_guard():
    """Day 2. Joint calibration of thousands of items is refused."""
    big = np.ones((400, 10), dtype=int)
    with pytest.raises(ResponseMatrixError, match="batches"):
        validate_matrix(big, 400, 10)
