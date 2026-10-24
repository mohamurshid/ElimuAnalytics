"""
IRT engine. Thin wrapper over `girth` 2-PL MMLE + EAP.

Every rule in this module came out of the Phase 0 spike and is enforced here
rather than documented and forgotten. See 01_HANDOVER/PHASE0_SPIKE_SUMMARY.md.

  Day 1  response matrix must be ITEMS x STUDENTS. girth does not error on the
         wrong orientation - it calibrates nonsense silently.
  Day 1  responses must be integer 0/1. Booleans cause internal errors.
  Day 1  missing responses are girth.INVALID_RESPONSE (-99999), never NaN.
  Day 3  no confident theta below ~5-10 answered items per strand. At one item
         per learner the ability/raw-score correlation was 0.380; at ten it was
         0.746. Flagging a child on fewer is flagging noise.
  Day 2  calibrate per strand in batches of 100-300 items, never one joint
         calibration (100 items 8.3s, 200 items 16.8s, 400 items 90.1s).
"""

from __future__ import annotations

import numpy as np
from girth import INVALID_RESPONSE, ability_eap, twopl_mml

# Day 3. Below MIN_RESPONSES nothing is shown at all; between MIN and CONFIDENT
# a theta is shown but marked provisional and the learner is never flagged.
MIN_RESPONSES = 5
CONFIDENT_RESPONSES = 10

# Day 2. Enforced as a guard here; batching itself arrives in Phase 2.
MAX_ITEMS_PER_CALIBRATION = 300

# KICD's four-level rubric (Day 4 - these tier names are KICD's own wording,
# not invented). Cut points are provisional and must be set from real class
# data in Phase 2; they are named here so there is one place to change them.
TIER_CUTS = [
    (1.0, "Exceeds expectation"),
    (0.0, "Meets expectation"),
    (-1.0, "Approaches expectation"),
    (float("-inf"), "Below expectation"),
]


class ResponseMatrixError(ValueError):
    """Raised when a response matrix violates a rule the spike established."""


def validate_matrix(responses: np.ndarray, n_items: int, n_students: int) -> np.ndarray:
    """Fail loudly on exactly the three things girth accepts silently.

    n_items and n_students are passed in explicitly rather than inferred,
    because a square-ish matrix gives no way to detect a transposed one.
    """
    if responses.dtype == bool:
        raise ResponseMatrixError(
            "Responses are boolean. girth requires integer 0/1 (Day 1 finding)."
        )
    if np.issubdtype(responses.dtype, np.floating) and np.isnan(responses).any():
        raise ResponseMatrixError(
            "Response matrix contains NaN. Missing responses must be "
            f"girth.INVALID_RESPONSE ({INVALID_RESPONSE}), not NaN (Day 1 finding)."
        )
    if responses.shape != (n_items, n_students):
        raise ResponseMatrixError(
            f"Response matrix is {responses.shape}, expected "
            f"({n_items}, {n_students}). girth needs ITEMS x STUDENTS and will "
            "calibrate a transposed matrix without complaining (Day 1 finding)."
        )
    if n_items > MAX_ITEMS_PER_CALIBRATION:
        raise ResponseMatrixError(
            f"{n_items} items in one calibration. Calibrate per strand in "
            f"batches of at most {MAX_ITEMS_PER_CALIBRATION} (Day 2 finding)."
        )
    valid = (responses == 0) | (responses == 1) | (responses == INVALID_RESPONSE)
    if not valid.all():
        raise ResponseMatrixError(
            "Response matrix contains values other than 0, 1 and INVALID_RESPONSE."
        )
    return responses.astype(int)


def answered_items(matrix: np.ndarray) -> np.ndarray:
    """True for each item (row) at least one learner has answered."""
    return (matrix != INVALID_RESPONSE).any(axis=1)


def calibrate(responses: np.ndarray, n_items: int, n_students: int) -> dict:
    """Estimate item difficulty and discrimination for one strand.

    An item nobody has answered yet carries no information, and girth fails
    outright on one (found 24 October: a question approved after the class
    had answered the others took down the heatmap). So it is left out, and
    its parameters come back as NaN until it has answers.
    """
    matrix = validate_matrix(responses, n_items, n_students)
    rows = answered_items(matrix)
    difficulty = np.full(n_items, np.nan)
    discrimination = np.full(n_items, np.nan)
    if rows.any():
        result = twopl_mml(matrix[rows])
        difficulty[rows] = np.asarray(result["Difficulty"], dtype=float)
        discrimination[rows] = np.asarray(result["Discrimination"], dtype=float)
    return {"difficulty": difficulty, "discrimination": discrimination}


def estimate_abilities(matrix: np.ndarray, params: dict) -> np.ndarray:
    """EAP ability for every learner, from the items that have answers and
    parameters. Items without either say nothing about anyone."""
    difficulty = np.asarray(params["difficulty"], dtype=float)
    discrimination = np.asarray(params["discrimination"], dtype=float)
    rows = answered_items(matrix) & ~np.isnan(difficulty) & ~np.isnan(discrimination)
    if not rows.any():
        return np.zeros(matrix.shape[1])
    return np.asarray(
        ability_eap(matrix[rows], difficulty[rows], discrimination[rows]), dtype=float
    )


def _usable(params: dict | None, matrix: np.ndarray) -> bool:
    """Stored parameters will do only if every answered item has them."""
    if params is None:
        return False
    rows = answered_items(matrix)
    return not (
        np.isnan(np.asarray(params["difficulty"], dtype=float)[rows]).any()
        or np.isnan(np.asarray(params["discrimination"], dtype=float)[rows]).any()
    )


def responses_answered(responses: np.ndarray, student_index: int) -> int:
    """How many items this learner actually answered in this strand."""
    column = responses[:, student_index]
    return int(np.count_nonzero(column != INVALID_RESPONSE))


def tier_for(theta: float) -> str:
    for cut, name in TIER_CUTS:
        if theta >= cut:
            return name
    return TIER_CUTS[-1][1]


def diagnose_all(
    responses: np.ndarray,
    n_items: int,
    n_students: int,
    params: dict | None = None,
) -> list[dict]:
    """Diagnose every learner from ONE calibration.

    `diagnose` calibrates the strand each time it is called, which is correct
    for a single learner and quadratic for a class: assessing forty learners ran
    forty calibrations of the same matrix. Calibration is a property of the
    strand, not of the learner, so it happens once here and the EAP step is
    vectorised across the class.

    `params` are stored item parameters (`difficulty`, `discrimination`, in
    the matrix's row order, NaN where an item has none). If every answered
    item has them, nothing is calibrated: the EAP step
    alone takes about 3 ms for a class, against 1 to 3 s for one calibration
    (measured 24 October, 12 to 50 items x 40 learners).
    """
    matrix = validate_matrix(responses, n_items, n_students)
    if not _usable(params, matrix):
        params = calibrate(matrix, n_items, n_students)
    abilities = estimate_abilities(matrix, params)

    out = []
    for idx in range(n_students):
        answered = responses_answered(matrix, idx)
        if answered < MIN_RESPONSES:
            out.append({
                "theta": None, "tier": None, "answered": answered,
                "confident": False, "flaggable": False,
                "message": (
                    f"{answered} item(s) answered. At least {MIN_RESPONSES} are "
                    "needed before an ability estimate means anything."
                ),
            })
            continue
        theta = float(abilities[idx])
        confident = answered >= CONFIDENT_RESPONSES
        out.append({
            "theta": round(theta, 3),
            "tier": tier_for(theta),
            "answered": answered,
            "confident": confident,
            "flaggable": bool(confident and theta < 0.0),
            "message": (
                "Estimate is provisional: "
                f"{answered} of {CONFIDENT_RESPONSES} items needed for confidence."
                if not confident
                else f"Based on {answered} answered items."
            ),
        })
    return out


def diagnose(
    responses: np.ndarray, n_items: int, n_students: int, student_index: int
) -> dict:
    """Full pipeline for one learner: calibrate, estimate theta, apply the
    Day 3 evidence threshold, map onto KICD's rubric."""
    matrix = validate_matrix(responses, n_items, n_students)
    answered = responses_answered(matrix, student_index)

    if answered < MIN_RESPONSES:
        # Day 3. Not a failure - an honest refusal. Below this, theta is noise.
        return {
            "theta": None,
            "tier": None,
            "answered": answered,
            "confident": False,
            "flaggable": False,
            "message": (
                f"{answered} item(s) answered. At least {MIN_RESPONSES} are needed "
                "before an ability estimate means anything."
            ),
        }

    params = calibrate(matrix, n_items, n_students)
    theta = float(estimate_abilities(matrix, params)[student_index])
    confident = answered >= CONFIDENT_RESPONSES

    return {
        "theta": round(theta, 3),
        "tier": tier_for(theta),
        "answered": answered,
        "confident": confident,
        # Flagging needs a confident estimate AND (in Phase 2) a second
        # consecutive assessment below threshold.
        "flaggable": bool(confident and theta < 0.0),
        "message": (
            "Estimate is provisional: "
            f"{answered} of {CONFIDENT_RESPONSES} items needed for confidence."
            if not confident
            else f"Based on {answered} answered items."
        ),
    }
