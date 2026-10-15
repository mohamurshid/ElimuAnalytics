"""
Phase 5 retrieval tests: the similarity floor, and the shape of the query.

The floor is the part worth testing without a database. It is the rule that
stopped the Day 5 spike from putting a plants chunk scoring 0.133 into the
prompt for a heat-transfer learner alongside the real match at 0.355, and a
report built on that prompt recommended plant activities to a teacher.

The pgvector query itself cannot be exercised here: curriculum_chunk is
excluded from the SQLite test schema because pgvector has no SQLite equivalent
(see test_repository.py). `python -m app.retrieval --check` covers it against
the real database, and compares pgvector's ranking against numpy's on the same
stored vectors.
"""

from __future__ import annotations

import pytest
from app.retrieval import FLOOR_ABS, FLOOR_REL, Retrieved, apply_floor


def result(similarity: float, label: str = "chunk") -> Retrieved:
    return Retrieved(
        chunk_id=label,
        grade="Grade 5",
        learning_area="Science and Technology",
        strand="3.0 Force and Energy",
        sub_strand=label,
        syllabus_text=label,
        source_id=label,
        source_row=0,
        similarity=similarity,
    )


def test_the_spike_case_drops_the_weak_second_chunk():
    # The exact numbers that motivated the floor: 0.355 for Heat Transfer,
    # 0.133 for Classification of plants.
    kept = apply_floor([result(0.355, "heat"), result(0.133, "plants")])
    assert [r.sub_strand for r in kept] == ["heat"]


def test_a_genuinely_close_second_chunk_is_admitted():
    kept = apply_floor([result(0.60, "first"), result(0.55, "second")])
    assert [r.sub_strand for r in kept] == ["first", "second"]


def test_the_best_match_is_always_kept_even_when_weak():
    """A weak best match is the caller's problem, not a reason to return nothing.

    Returning an empty list for a low-scoring corpus would be indistinguishable
    from an empty corpus, and the condition that actually matters - "the
    curriculum does not cover this" - is one the report prompt already handles
    by refusing. The wrong-context control in the Day 5 spike showed the model
    naming the mismatch and declining, which is the behaviour to preserve.
    """
    kept = apply_floor([result(0.05, "barely")])
    assert [r.sub_strand for r in kept] == ["barely"]


def test_relative_floor_binds_when_the_top_score_is_high():
    # rel: 0.50 x 0.90 = 0.45, which is above the absolute floor of 0.25.
    kept = apply_floor([result(0.90, "top"), result(0.40, "below-relative")])
    assert [r.sub_strand for r in kept] == ["top"]


def test_absolute_floor_binds_when_the_top_score_is_low():
    # rel: 0.50 x 0.30 = 0.15, which is below the absolute floor of 0.25, so
    # the absolute floor is what excludes the second chunk.
    assert FLOOR_REL * 0.30 < FLOOR_ABS
    kept = apply_floor([result(0.30, "top"), result(0.20, "below-absolute")])
    assert [r.sub_strand for r in kept] == ["top"]


def test_a_candidate_exactly_on_the_cutoff_is_admitted():
    cutoff = max(FLOOR_ABS, FLOOR_REL * 0.80)
    kept = apply_floor([result(0.80, "top"), result(cutoff, "exactly-on")])
    assert [r.sub_strand for r in kept] == ["top", "exactly-on"]


def test_floor_on_nothing_returns_nothing():
    assert apply_floor([]) == []


@pytest.mark.parametrize("third", [0.60, 0.10])
def test_every_candidate_after_the_first_is_judged_independently(third):
    kept = apply_floor([result(0.70, "a"), result(0.65, "b"), result(third, "c")])
    expected = ["a", "b", "c"] if third >= max(FLOOR_ABS, FLOOR_REL * 0.70) else ["a", "b"]
    assert [r.sub_strand for r in kept] == expected


def test_floors_are_the_spike_values():
    # If these drift from the spike, the retrieval measurements in Chapter 5
    # stop describing the shipped system.
    assert (FLOOR_ABS, FLOOR_REL) == (0.25, 0.50)
