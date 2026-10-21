"""
Quizzes of a set length: choosing the questions, and keeping the choice.

Agreed 21 October: the teacher picks a length (5, 10 or 15, or every
question); the app picks which questions; the whole class gets the same set,
on a device or on paper. The set is saved (models.QuizSet) so the printed
sheet, the marking grid and every learner's turn on the device agree.

**How questions are chosen** (choose(), pure and unit-tested):

  1. Order the candidates by difficulty, easy to hard. A question not yet
     calibrated has no difficulty; it is placed in the middle, where an
     unknown question belongs.
  2. Cut that order into as many bands as the quiz has questions, so the
     quiz spreads across the range rather than bunching at one end.
  3. From each band take the question with the fewest answers recorded, so
     new questions get answered and can be calibrated. Ties go by id, so the
     choice is the same every time for the same data.

Only approved questions are candidates (item_status.SERVED). A device quiz
also needs options and a key, since the server marks what the learner taps;
a paper quiz may include a text-only question that the teacher reads out.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import repository as repo
from .assessments import QuizItemOut
from .auth import current_teacher
from .db import get_session
from .item_status import SERVED
from .models import ClassStrand, Item, QuizSet, Response, Strand, Teacher

router = APIRouter(prefix="/api", tags=["quizzes"])

Mode = Literal["device", "paper"]


@dataclass(frozen=True)
class Candidate:
    item_id: str
    difficulty: float | None
    answers: int


def choose(candidates: Sequence[Candidate], length: int | None) -> list[str]:
    """Item ids for a quiz of `length` (None: every candidate), easy to hard."""

    def by_difficulty(c: Candidate) -> tuple:
        return (c.difficulty if c.difficulty is not None else 0.0, c.item_id)

    ordered = sorted(candidates, key=by_difficulty)
    if length is None or length >= len(ordered):
        return [c.item_id for c in ordered]
    chosen = []
    for band in range(length):
        start = band * len(ordered) // length
        end = (band + 1) * len(ordered) // length
        chosen.append(min(ordered[start:end], key=lambda c: (c.answers, c.item_id)))
    return [c.item_id for c in sorted(chosen, key=by_difficulty)]


# --- endpoints -------------------------------------------------------------
class QuizCreate(BaseModel):
    strand_id: uuid.UUID
    # 5, 10 or 15; null for every question.
    length: Literal[5, 10, 15] | None = None
    mode: Mode = "device"


class QuizSetOut(BaseModel):
    """What a learner's device may see: no key, no mark scheme."""

    quiz_id: str
    class_id: str
    strand_id: str
    strand: str
    mode: str
    created_at: str | None
    items: list[QuizItemOut]
    # Each item's number in the quiz as made, 1-based. Unchanged when a
    # question is withdrawn, so the marking grid's column 4 is still the
    # sheet's question 4.
    numbers: list[int]
    # Questions chosen when the quiz was made that have since been reported
    # or retired. They are left out, as they are from every new quiz, and
    # counted so the screen can say why the quiz is shorter than printed.
    withdrawn: int


class QuizSummary(BaseModel):
    quiz_id: str
    strand_id: str
    strand: str
    mode: str
    questions: int
    created_at: str | None


def _iso(moment) -> str | None:
    return moment.isoformat() if moment else None


def _out(session: Session, quiz: QuizSet) -> QuizSetOut:
    strand = session.get(Strand, quiz.strand_id)
    items = {
        str(i.item_id): i
        for i in session.scalars(
            select(Item).where(Item.item_id.in_([uuid.UUID(x) for x in quiz.item_ids]))
        )
    }
    served = [
        (n, items[x])
        for n, x in enumerate(quiz.item_ids, start=1)
        if x in items and items[x].status in SERVED
    ]
    return QuizSetOut(
        quiz_id=str(quiz.quiz_id),
        class_id=str(quiz.class_id),
        strand_id=str(quiz.strand_id),
        strand=strand.name if strand else "",
        mode=quiz.mode,
        created_at=_iso(quiz.created_at),
        items=[
            QuizItemOut(
                item_id=str(i.item_id),
                question_text=i.question_text,
                options=list(i.options or []),
            )
            for _n, i in served
        ],
        numbers=[n for n, _i in served],
        withdrawn=len(quiz.item_ids) - len(served),
    )


@router.post("/classrooms/{class_id}/quizzes", response_model=QuizSetOut, status_code=201)
def create_quiz(
    class_id: uuid.UUID,
    body: QuizCreate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> QuizSetOut:
    classroom = repo.classroom_in_school(session, class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    if session.get(ClassStrand, (class_id, body.strand_id)) is None:
        raise HTTPException(status_code=404, detail="This class is not assessed on that strand")

    stmt = select(Item).where(Item.strand_id == body.strand_id, Item.status.in_(SERVED))
    items = list(session.scalars(stmt))
    if body.mode == "device":
        items = [i for i in items if i.options and i.correct_option is not None]
    if not items:
        raise HTTPException(
            status_code=409,
            detail="This strand has no approved questions"
            + (" that can be answered on a device" if body.mode == "device" else "")
            + " yet.",
        )
    answers = dict(
        session.execute(
            select(Response.item_id, func.count(Response.response_id))
            .where(Response.item_id.in_([i.item_id for i in items]))
            .group_by(Response.item_id)
        ).all()
    )
    chosen = choose(
        [Candidate(str(i.item_id), i.difficulty_b, answers.get(i.item_id, 0)) for i in items],
        body.length,
    )
    quiz = QuizSet(
        class_id=class_id, strand_id=body.strand_id, item_ids=chosen,
        mode=body.mode, created_by=teacher.teacher_id,
    )
    session.add(quiz)
    session.commit()
    return _out(session, quiz)


def _quiz_in_school(session: Session, quiz_id: uuid.UUID, teacher: Teacher) -> QuizSet:
    quiz = session.get(QuizSet, quiz_id)
    if quiz is None or repo.classroom_in_school(
        session, quiz.class_id, teacher.school_id
    ) is None:
        raise HTTPException(status_code=404, detail="No such quiz")
    return quiz


@router.get("/quizzes/{quiz_id}", response_model=QuizSetOut)
def get_quiz(
    quiz_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> QuizSetOut:
    return _out(session, _quiz_in_school(session, quiz_id, teacher))


@router.get("/classrooms/{class_id}/quizzes", response_model=list[QuizSummary])
def list_quizzes(
    class_id: uuid.UUID,
    strand_id: uuid.UUID | None = Query(default=None),
    mode: Mode | None = Query(default=None),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[QuizSummary]:
    """The class's recent quizzes, newest first - so a printed quiz can be
    found again to mark."""
    if repo.classroom_in_school(session, class_id, teacher.school_id) is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    stmt = select(QuizSet).where(QuizSet.class_id == class_id)
    if strand_id:
        stmt = stmt.where(QuizSet.strand_id == strand_id)
    if mode:
        stmt = stmt.where(QuizSet.mode == mode)
    quizzes = list(session.scalars(stmt.order_by(QuizSet.created_at.desc()).limit(10)))
    names = {s.strand_id: s.name for s in repo.class_strands(session, class_id)}
    return [
        QuizSummary(
            quiz_id=str(q.quiz_id), strand_id=str(q.strand_id),
            strand=names.get(q.strand_id, ""), mode=q.mode,
            questions=len(q.item_ids), created_at=_iso(q.created_at),
        )
        for q in quizzes
    ]
