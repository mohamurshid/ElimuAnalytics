"""
Hardcoded stand-in for the item bank and response store.

Phase 1 has no database on purpose. This module is the seam where PostgreSQL
arrives in Phase 2: replace these functions, change nothing else.

The strand and sub-strand names are real KICD Grade 5 Science & Technology
(Revised 2024), matching the curriculum chunks used in the Day 5 RAG spike.
"""

from __future__ import annotations

import numpy as np
from girth import INVALID_RESPONSE

STRAND = "3.0 Force and Energy"
SUB_STRAND = "3.3 Heat Transfer"

ITEMS = [
    "A metal spoon is left in hot porridge. What happens to the handle?",
    "Which keeps hot food warm for longer: a metal tin or a clay pot?",
    "Name one good conductor of heat found in the kitchen.",
    "Why is the handle of a cooking pot covered with plastic?",
    "How does heat reach your hand when you sit near a fire?",
    "Which travels through a metal rod: conduction or radiation?",
    "Name one poor conductor of heat used to hold hot things.",
    "Give one safety precaution when handling hot utensils.",
    "Why does warm air rise above a cooking fire?",
    "Which mode of heat transfer needs no material to travel through?",
    "Name one material that could be used to make oven gloves.",
    "State one use of heat transfer in preserving food.",
]
# Twelve items, deliberately: CONFIDENT_RESPONSES is 10, so a full-quiz learner
# clears the Day 3 confidence bar and a partial learner does not. Both paths
# are exercised by the skeleton rather than only the refusal path.

N_ITEMS = len(ITEMS)
N_STUDENTS = 40

LEARNERS = ["Chebet K.", "Amina W.", "Otieno J."]
# Index 0 is the struggling learner, 1 is mid-range, 2 has answered almost
# nothing - which is what exercises the Day 3 minimum-responses rule.
FOCUS_LEARNERS = {0: "Chebet K.", 1: "Amina W.", 2: "Otieno J."}


def _simulated_class() -> np.ndarray:
    """A deterministic class of 40 learners. Real responses replace this in
    Phase 2; the shape and dtype are already what girth requires."""
    rng = np.random.default_rng(169962)

    difficulty = rng.normal(0.0, 1.0, N_ITEMS)
    discrimination = rng.uniform(0.8, 2.0, N_ITEMS)
    theta = rng.normal(0.0, 1.0, N_STUDENTS)
    theta[0] = -1.8   # the flagged learner from the Day 5 spike
    theta[1] = 0.4
    theta[2] = -0.5

    # ITEMS x STUDENTS from the start (Day 1 finding).
    p = 1.0 / (1.0 + np.exp(-discrimination[:, None] * (theta[None, :] - difficulty[:, None])))
    responses = (rng.random((N_ITEMS, N_STUDENTS)) < p).astype(int)

    # Learner 2 sat out most of the quiz: 3 answered items, below MIN_RESPONSES.
    responses[3:, 2] = INVALID_RESPONSE

    return responses


RESPONSES = _simulated_class()


def response_matrix() -> np.ndarray:
    return RESPONSES


def learner_name(index: int) -> str:
    return FOCUS_LEARNERS.get(index, f"Learner {index}")
