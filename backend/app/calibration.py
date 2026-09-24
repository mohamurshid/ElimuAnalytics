"""
Calibration and assessment: the diagnostic loop, persisted.

Phase 1 calibrated on every request and threw the parameters away. That is
fine for one strand of twelve items and impossible for a real item bank, where
Day 2 measured calibration cost rising non-linearly with item count - 8.3
seconds for 100 items, 16.8 for 200, 90.1 for 400.

So calibration is now a separate, deliberate operation. Item parameters are
written back to the database and reused until the strand is recalibrated.
Assessment reads those parameters, estimates ability, records the estimate, and
raises a flag only when the design's two-consecutive-assessment rule is met.
"""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .irt import (
    CONFIDENT_RESPONSES,
    MAX_ITEMS_PER_CALIBRATION,
    MIN_RESPONSES,
    calibrate,
    tier_for,
)
from .models import AbilityScore, GapFlag, Item, Strand
from .repository import build_response_matrix, consecutive_low_assessments

# Day 2. Items below this discrimination carry little diagnostic value and are
# excluded from the active bank, as specified in Chapter 3.
MIN_DISCRIMINATION = 0.3

# Two consecutive below-threshold assessments before a learner is flagged.
CONSECUTIVE_FOR_FLAG = 2
FLAG_THRESHOLD = 0.0


def calibrate_strand(
    session: Session, strand_id: uuid.UUID, class_id: uuid.UUID | None = None
) -> dict:
    """Estimate item parameters for one strand and persist them.

    Calibration is per strand by design, not one joint calibration across the
    whole bank: the cost is non-linear in item count, and the strand is the
    diagnostic unit the CBE framework reports on anyway.
    """
    matrix, item_ids, student_ids = build_response_matrix(session, strand_id, class_id)
    if not item_ids:
        raise ValueError("Strand has no items")
    if len(item_ids) > MAX_ITEMS_PER_CALIBRATION:
        raise ValueError(
            f"{len(item_ids)} items exceeds the {MAX_ITEMS_PER_CALIBRATION}-item "
            "batch ceiling; split the strand before calibrating"
        )

    params = calibrate(matrix, len(item_ids), len(student_ids))
    difficulty = np.asarray(params["difficulty"], dtype=float)
    discrimination = np.asarray(params["discrimination"], dtype=float)

    low_discrimination = []
    for n, item_id in enumerate(item_ids):
        item = session.get(Item, item_id)
        item.difficulty_b = float(difficulty[n])
        item.discrimination_a = float(discrimination[n])
        if item.discrimination_a < MIN_DISCRIMINATION:
            low_discrimination.append(item_id)
    session.commit()

    return {
        "strand_id": str(strand_id),
        "items_calibrated": len(item_ids),
        "students_in_calibration": len(student_ids),
        "mean_difficulty": round(float(difficulty.mean()), 3),
        "mean_discrimination": round(float(discrimination.mean()), 3),
        "low_discrimination_items": [str(i) for i in low_discrimination],
        "low_discrimination_count": len(low_discrimination),
    }


def assess_strand(
    session: Session, strand_id: uuid.UUID, class_id: uuid.UUID | None = None
) -> dict:
    """Estimate ability for every learner in the strand, persist, and flag.

    Two rules from Phase 0 are enforced together here, and the order matters:
    a learner below the minimum-responses threshold gets no recorded estimate
    at all, so they cannot subsequently be flagged on the strength of noise.
    """
    from .irt import diagnose_all  # local import keeps the module import cycle-free

    matrix, item_ids, student_ids = build_response_matrix(session, strand_id, class_id)
    if not student_ids:
        raise ValueError("Strand has no learners")

    recorded = skipped = flagged = 0
    new_flags: list[dict] = []

    # One calibration for the whole class, not one per learner.
    results = diagnose_all(matrix, len(item_ids), len(student_ids))

    for idx, student_id in enumerate(student_ids):
        result = results[idx]

        if result["theta"] is None:
            # Below MIN_RESPONSES. Nothing is written: an absent estimate is
            # honest, a recorded one would look like evidence.
            skipped += 1
            continue

        session.add(
            AbilityScore(
                student_id=student_id,
                strand_id=strand_id,
                theta=result["theta"],
                items_answered=result["answered"],
            )
        )
        recorded += 1
    session.commit()

    # Flagging is a second pass, because it reads the history this pass wrote.
    for student_id in student_ids:
        run = consecutive_low_assessments(session, student_id, strand_id, FLAG_THRESHOLD)
        if run < CONSECUTIVE_FOR_FLAG:
            continue
        already = session.scalar(
            select(GapFlag).where(
                GapFlag.student_id == student_id,
                GapFlag.strand_id == strand_id,
                GapFlag.resolved.is_(False),
            )
        )
        if already:
            continue
        latest = session.scalars(
            select(AbilityScore)
            .where(
                AbilityScore.student_id == student_id,
                AbilityScore.strand_id == strand_id,
            )
            .order_by(AbilityScore.assessed_at.desc())
        ).first()
        session.add(
            GapFlag(
                student_id=student_id,
                strand_id=strand_id,
                severity=tier_for(latest.theta) if latest else "Below expectation",
            )
        )
        flagged += 1
        new_flags.append({"student_id": str(student_id), "consecutive": run})
    session.commit()

    strand = session.get(Strand, strand_id)
    return {
        "strand": strand.name if strand else str(strand_id),
        "learners": len(student_ids),
        "estimates_recorded": recorded,
        "skipped_insufficient_evidence": skipped,
        "minimum_responses": MIN_RESPONSES,
        "confident_responses": CONFIDENT_RESPONSES,
        "new_flags": flagged,
        "flag_detail": new_flags,
    }


def open_flags(session: Session, strand_id: uuid.UUID | None = None) -> list[GapFlag]:
    stmt = select(GapFlag).where(GapFlag.resolved.is_(False))
    if strand_id:
        stmt = stmt.where(GapFlag.strand_id == strand_id)
    return list(session.scalars(stmt.order_by(GapFlag.flagged_at.desc())))
