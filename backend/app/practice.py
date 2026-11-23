"""
Practice sets: a few questions chosen for one learner from their own level.

A report says where a learner is on a sub-strand. A practice set is the next
step for that learner, chosen by the same 2-PL model that placed them there.

**How questions are chosen** (choose_practice(), pure and unit-tested):

  1. Only approved questions the learner has not answered. The response
     matrix holds one answer per learner and question, so a repeat could not
     be recorded anyway, and a fresh question is what moves the estimate.
  2. Only questions with stored parameters (difficulty b, discrimination
     a > 0). A question not yet calibrated has no predicted chance, so it
     cannot be placed against this learner.
  3. For each, the 2-PL chance that this learner answers correctly:
         P = 1 / (1 + exp(-a (theta - b)))
     and the questions closest to TARGET are taken. At 0.7 a question is
     within reach but not yet secure: hard enough to be worth practising,
     easy enough that the learner succeeds more often than not. A question
     at P = 0.5 says the most about the learner's level, which is what a
     test wants; practice wants a little more success than that. A
     question the learner is all but certain to get right (SECURE, 0.95 or
     more) is left out: practising it teaches them nothing, so a set may be
     shorter than asked for.
  4. Ties go by item id, so the same data gives the same set. The set is
     ordered by this learner's chance, most likely first, so they start
     with what they can do. (Ordering by difficulty b alone would not: two
     questions of different discrimination can swap places for a learner
     far from both.)

When the bank has nothing near the target for a learner - a learner far
below every question, say - the nearest questions are still returned, with
their real chances, and the page says the bank needs easier questions.

The set is saved as a quiz (models.QuizSet, mode "practice") so the device
session asks exactly the questions the teacher saw. Answers are recorded as
any other answers are, so the learner's level moves with them, and the next
practice set is chosen from the new level.

Nothing here calls a model or writes text. The learner's own ability and the
questions' own parameters decide, and every question was approved by a
teacher before it could be chosen.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .db import get_session
from .irt import diagnose_all
from .item_status import SERVED
from .models import ClassStrand, Item, QuizSet, Response, Strand, Teacher

router = APIRouter(prefix="/api", tags=["practice"])

PRACTICE = "practice"
TARGET = 0.7
SECURE = 0.95
DEFAULT_LENGTH = 5


@dataclass(frozen=True)
class Calibrated:
    item_id: str
    difficulty: float | None
    discrimination: float | None


def chance(theta: float, difficulty: float, discrimination: float) -> float:
    """The 2-PL probability of a correct answer (Equation 5.1)."""
    return 1.0 / (1.0 + math.exp(-discrimination * (theta - difficulty)))


def choose_practice(
    theta: float,
    candidates: Sequence[Calibrated],
    length: int = DEFAULT_LENGTH,
    target: float = TARGET,
) -> list[tuple[str, float]]:
    """(item id, predicted chance) for the `length` questions nearest the
    target chance, most likely first. Fewer if fewer can be placed."""
    placed = [
        (c, chance(theta, c.difficulty, c.discrimination))
        for c in candidates
        if c.difficulty is not None
        and c.discrimination is not None
        and c.discrimination > 0
    ]
    placed = [pair for pair in placed if pair[1] < SECURE]
    placed.sort(key=lambda pair: (abs(pair[1] - target), pair[0].item_id))
    chosen = placed[:length]
    chosen.sort(key=lambda pair: (-pair[1], pair[0].item_id))
    return [(c.item_id, p) for c, p in chosen]


# --- endpoint --------------------------------------------------------------
class PracticeIn(BaseModel):
    strand_id: uuid.UUID
    length: int = Field(default=DEFAULT_LENGTH, ge=3, le=10)


class PracticeItemOut(BaseModel):
    """The teacher's view of a chosen question: no key, no mark scheme."""

    item_id: str
    question_text: str
    # The model's predicted chance that this learner answers it correctly.
    chance: float


class PracticeOut(BaseModel):
    quiz_id: str
    class_id: str
    student_id: str
    strand_id: str
    strand: str
    theta: float
    tier: str
    target: float
    items: list[PracticeItemOut]
    # Approved questions this learner has not answered but that cannot be
    # placed yet because they have not been calibrated.
    uncalibrated: int


def _theta(session: Session, student_id: uuid.UUID, class_id: uuid.UUID,
           strand_id: uuid.UUID) -> dict | None:
    """This learner's current estimate on the strand, computed as the heatmap
    computes it: one calibration (or the stored parameters) for the class."""
    matrix, item_ids, student_ids = repo.build_response_matrix(session, strand_id, class_id)
    if not item_ids or student_id not in student_ids:
        return None
    results = diagnose_all(
        matrix, len(item_ids), len(student_ids),
        params=repo.stored_parameters(session, item_ids),
    )
    return results[student_ids.index(student_id)]


@router.post("/students/{student_id}/practice", response_model=PracticeOut, status_code=201)
def make_practice(
    student_id: uuid.UUID,
    body: PracticeIn,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> PracticeOut:
    student = repo.student_in_school(session, student_id, teacher.school_id)
    if student is None:
        raise HTTPException(status_code=404, detail="No such learner")
    strand = session.get(Strand, body.strand_id)
    if strand is None or session.get(ClassStrand, (student.class_id, body.strand_id)) is None:
        raise HTTPException(status_code=404, detail="This class is not assessed on that strand")
    if not student.is_active:
        raise HTTPException(status_code=409, detail="This learner has been withdrawn.")

    estimate = _theta(session, student.student_id, student.class_id, body.strand_id)
    if estimate is None or estimate["theta"] is None:
        answered = estimate["answered"] if estimate else 0
        raise HTTPException(
            status_code=409,
            detail=(
                f"{student.name} has answered {answered} question(s) on this sub-strand. "
                "A practice set is chosen from their level, which needs at least five "
                "answers. Give a quiz first."
            ),
        )
    theta = float(estimate["theta"])

    taken = set(
        session.scalars(
            select(Response.item_id).where(Response.student_id == student.student_id)
        )
    )
    # On a device the server marks the tap, so a question needs options and a key.
    fresh = [
        i for i in session.scalars(
            select(Item).where(Item.strand_id == body.strand_id, Item.status.in_(SERVED))
        )
        if i.item_id not in taken and i.options and i.correct_option is not None
    ]
    chosen = choose_practice(
        theta,
        [Calibrated(str(i.item_id), i.difficulty_b, i.discrimination_a) for i in fresh],
        body.length,
    )
    uncalibrated = sum(1 for i in fresh if i.difficulty_b is None or i.discrimination_a is None)
    if not chosen:
        if len(fresh) > uncalibrated:
            reason = (
                "every question they have not answered is one the model is all but "
                "certain they would get right. Write or draft harder questions."
            )
        elif uncalibrated:
            reason = (
                f"{uncalibrated} new question(s) have not been calibrated yet. Use "
                "Recalibrate on the class page once some learners have answered them."
            )
        else:
            reason = "they have answered every approved question. Write or draft more."
        raise HTTPException(
            status_code=409,
            detail=f"No question on this sub-strand can be chosen for {student.name}: {reason}",
        )

    quiz = QuizSet(
        class_id=student.class_id, strand_id=body.strand_id,
        item_ids=[item_id for item_id, _ in chosen],
        mode=PRACTICE, created_by=teacher.teacher_id,
    )
    session.add(quiz)
    session.commit()

    by_id = {str(i.item_id): i for i in fresh}
    return PracticeOut(
        quiz_id=str(quiz.quiz_id),
        class_id=str(student.class_id),
        student_id=str(student.student_id),
        strand_id=str(body.strand_id),
        strand=strand.name,
        theta=round(theta, 3),
        tier=estimate["tier"],
        target=TARGET,
        items=[
            PracticeItemOut(
                item_id=item_id,
                question_text=by_id[item_id].question_text,
                chance=round(p, 2),
            )
            for item_id, p in chosen
        ],
        uncalibrated=uncalibrated,
    )
