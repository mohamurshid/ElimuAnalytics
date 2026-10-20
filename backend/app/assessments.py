"""
Recording learner responses.

Until now the only responses in the database were seeded ones. This is the
endpoint a quiz interface submits to, and in Phase 4 it is also the endpoint a
tablet drains its offline queue into. Both uses shape it.

**Why a batch rather than one response per request.** A class of forty
learners answering twelve items is 480 rows. Sent individually over a weak
connection that is 480 chances to half-fail; sent as one batch it either
lands or it does not.

**Why the client supplies the identifier.** A device that submits and then
loses the connection before the reply arrives does not know whether the work
was recorded, so it retries. The server cannot tell that retry from a genuine
second submission of identical answers - they are byte-identical. Only the
device knows, so the device generates `client_batch_id` once and sends it with
every retry. It is `UNIQUE` in the database, so the duplicate is caught by a
constraint rather than by a check-then-insert that two concurrent retries
could both pass.

A duplicate submission is answered **200 with `duplicate: true`**, not an
error. The device did nothing wrong, and the outcome it wanted has already
happened.

**Why re-answering an item is refused.** The response matrix holds one cell
per learner-item pair. A second response to the same item would overwrite the
first, silently changing that learner's ability estimate and - because the
item is recalibrated from the whole class - everyone else's too. Re-assessment
of an already-answered item is not supported by this design, and saying so
with a 409 is better than accepting it and quietly moving the numbers.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .db import get_session
from .item_status import ANSWERABLE, DRAFT, SERVED
from .models import AssessmentBatch, Item, Response, Strand, Student, Teacher

router = APIRouter(prefix="/api/assessments", tags=["assessments"])

MAX_RESPONSES_PER_BATCH = 2000


class ResponseIn(BaseModel):
    """One answer, reported one of two ways.

    `correct` is a teacher's judgement: they ran the quiz on paper or aloud
    and know the outcome. `selected_option` is a learner's tap on a device,
    and the server decides whether it was right.

    The distinction is not cosmetic. A client that reports its own
    correctness can report whatever it likes, and a client that can mark
    answers has necessarily been told the key - which means the key is in the
    browser, where a curious learner can read it. So a learner's device sends
    only the option chosen, and never learns whether it was right.
    """

    student_id: uuid.UUID
    item_id: uuid.UUID
    correct: bool | None = None
    selected_option: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def exactly_one(self) -> ResponseIn:
        if (self.correct is None) == (self.selected_option is None):
            raise ValueError(
                "give either correct (a teacher's marking) or selected_option "
                "(a learner's answer), not both and not neither"
            )
        return self


class AssessmentIn(BaseModel):
    client_batch_id: uuid.UUID = Field(
        description="Generated on the device, once, and resent unchanged on every retry."
    )
    class_id: uuid.UUID
    strand_id: uuid.UUID
    responses: list[ResponseIn] = Field(min_length=1, max_length=MAX_RESPONSES_PER_BATCH)


class AssessmentOut(BaseModel):
    batch_id: str
    client_batch_id: str
    class_id: str
    strand_id: str
    responses_recorded: int
    duplicate: bool
    detail: str


def _reject(problems: list[str], status: int = 422) -> None:
    raise HTTPException(status_code=status, detail={"problems": problems})


@router.post("", response_model=AssessmentOut)
def record_assessment(
    body: AssessmentIn,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> AssessmentOut:
    # Idempotency first: a retry must not be re-validated against a database
    # that its own first attempt has already changed.
    existing = session.scalar(
        select(AssessmentBatch).where(
            AssessmentBatch.client_batch_id == body.client_batch_id
        )
    )
    if existing is not None:
        return AssessmentOut(
            batch_id=str(existing.batch_id),
            client_batch_id=str(existing.client_batch_id),
            class_id=str(existing.class_id),
            strand_id=str(existing.strand_id),
            responses_recorded=existing.response_count,
            duplicate=True,
            detail="This batch was already recorded. Nothing was changed.",
        )

    classroom = repo.classroom_in_school(session, body.class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    if session.get(Strand, body.strand_id) is None:
        raise HTTPException(status_code=404, detail="No such strand")

    # --- validate the whole batch before writing any of it -----------------
    enrolled = {
        s.student_id for s in repo.classroom_students(session, body.class_id)
    }
    items = {
        i.item_id: i
        for i in session.scalars(
            select(Item).where(Item.strand_id == body.strand_id)
        )
    }

    problems: list[str] = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()

    for r in body.responses:
        if r.student_id not in enrolled:
            problems.append(f"learner {r.student_id} is not enrolled in this classroom")
        item = items.get(r.item_id)
        if item is None:
            problems.append(f"item {r.item_id} is not in this strand")
        elif item.status == DRAFT:
            problems.append(f"item {r.item_id} has not been approved, so it cannot be answered")
        elif item.status not in ANSWERABLE:
            problems.append(f"item {r.item_id} has been withdrawn from the bank")
        if r.selected_option is not None and item is not None:
            if item.correct_option is None or not item.options:
                problems.append(
                    f"item {r.item_id} has no answer options, so an answer "
                    "cannot be marked - a teacher must mark it"
                )
            elif r.selected_option >= len(item.options):
                problems.append(
                    f"item {r.item_id} has {len(item.options)} options; "
                    f"option {r.selected_option} does not exist"
                )

        pair = (r.student_id, r.item_id)
        if pair in seen:
            problems.append(f"learner {r.student_id} answers item {r.item_id} twice in this batch")
        seen.add(pair)

    if problems:
        _reject(sorted(set(problems))[:20])

    already = session.execute(
        select(Response.student_id, Response.item_id).where(
            Response.item_id.in_([r.item_id for r in body.responses])
        )
    ).all()
    clashes = sorted(
        f"learner {sid} has already answered item {iid}"
        for sid, iid in already
        if (sid, iid) in seen
    )
    if clashes:
        raise HTTPException(
            status_code=409,
            detail={
                "problems": clashes[:20],
                "reason": (
                    "The response matrix holds one cell per learner and item. "
                    "Recording a second answer would overwrite the first and "
                    "change ability estimates derived from it."
                ),
            },
        )

    # --- write --------------------------------------------------------------
    batch = AssessmentBatch(
        client_batch_id=body.client_batch_id,
        class_id=body.class_id,
        strand_id=body.strand_id,
        teacher_id=teacher.teacher_id,
        response_count=len(body.responses),
    )
    session.add(batch)
    try:
        session.flush()
    except IntegrityError:
        # Two retries arriving together: the unique constraint settles it.
        session.rollback()
        settled = session.scalar(
            select(AssessmentBatch).where(
                AssessmentBatch.client_batch_id == body.client_batch_id
            )
        )
        if settled is None:
            raise
        return AssessmentOut(
            batch_id=str(settled.batch_id),
            client_batch_id=str(settled.client_batch_id),
            class_id=str(settled.class_id),
            strand_id=str(settled.strand_id),
            responses_recorded=settled.response_count,
            duplicate=True,
            detail="This batch was already recorded. Nothing was changed.",
        )

    session.add_all(
        Response(
            student_id=r.student_id,
            item_id=r.item_id,
            # Marked here, not on the device. For a teacher's submission this
            # is simply their judgement passed through; for a learner's it is
            # the comparison the device was never told how to make.
            correctness=(
                r.correct
                if r.correct is not None
                else r.selected_option == items[r.item_id].correct_option
            ),
            selected_option=r.selected_option,
            batch_id=batch.batch_id,
        )
        for r in body.responses
    )
    session.commit()
    session.refresh(batch)

    return AssessmentOut(
        batch_id=str(batch.batch_id),
        client_batch_id=str(batch.client_batch_id),
        class_id=str(batch.class_id),
        strand_id=str(batch.strand_id),
        responses_recorded=batch.response_count,
        duplicate=False,
        detail=(
            f"Recorded {batch.response_count} responses. Recalibrate the strand "
            "to fold them into ability estimates."
        ),
    )


class QuizItemOut(BaseModel):
    """What a learner's device is allowed to know about an item.

    There is deliberately no `correct_option` field on this model, and that
    absence is the security control. It is a separate schema from `ItemOut`
    rather than the same one with a field omitted at runtime, because a
    field that must never be serialised is safer as a field that does not
    exist than as one someone remembers to strip.
    """

    item_id: str
    question_text: str
    options: list[str]


class QuizOut(BaseModel):
    class_id: str
    strand_id: str
    strand: str
    items: list[QuizItemOut]


@router.get("/quiz/{class_id}/{strand_id}", response_model=QuizOut)
def quiz_items(
    class_id: uuid.UUID,
    strand_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> QuizOut:
    """The questions a learner answers, without the answers.

    Authenticated as the teacher, because the tablet is: there are no learner
    accounts, and identity rests on the teacher selecting a name before
    handing the device over. That assumption is deliberate - issuing
    credentials to primary-school children is a far larger data-protection
    surface than it is worth here - and it is recorded as a limitation rather
    than hidden.

    What this endpoint does enforce is that the device learns nothing it does
    not need: one strand's questions and their options, no answer key, no
    other learner, no estimates.
    """
    if repo.classroom_in_school(session, class_id, teacher.school_id) is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    strand = session.get(Strand, strand_id)
    if strand is None:
        raise HTTPException(status_code=404, detail="No such strand")

    items = [
        item
        for item in session.scalars(
            select(Item)
            # Approved only: never a draft nobody has checked, nor a question
            # someone has reported as wrong.
            .where(Item.strand_id == strand_id, Item.status.in_(SERVED))
            .order_by(Item.item_id)
        )
        # An item with no options cannot be delivered to a learner. It is
        # still a perfectly good item for a teacher to mark.
        if item.options and item.correct_option is not None
    ]

    return QuizOut(
        class_id=str(class_id),
        strand_id=str(strand_id),
        strand=strand.name,
        items=[
            QuizItemOut(
                item_id=str(item.item_id),
                question_text=item.question_text,
                options=list(item.options or []),
            )
            for item in items
        ],
    )


class AnsweredOut(BaseModel):
    class_id: str
    strand_id: str
    # "<student_id>:<item_id>" - a flat key, because JSON object keys cannot
    # be tuples and the client only ever asks "is this pair taken?".
    answered: list[str]


@router.get("/answered/{class_id}/{strand_id}", response_model=AnsweredOut)
def answered_pairs(
    class_id: uuid.UUID,
    strand_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> AnsweredOut:
    """Which learner-item pairs in this strand already have a response.

    A marking grid needs this before it can be honest. Without it the
    interface cannot tell which cells are already recorded, a teacher ticks
    one of them, and the whole batch is refused with a 409 naming pairs they
    had no way of knowing about. With it, those cells are locked and the
    rejection never arises.

    Re-answering is refused rather than allowed because the response matrix
    holds one cell per learner and item; a second answer would overwrite the
    first and move estimates derived from it.
    """
    if repo.classroom_in_school(session, class_id, teacher.school_id) is None:
        raise HTTPException(status_code=404, detail="No such classroom")

    enrolled = {s.student_id for s in repo.classroom_students(session, class_id)}
    rows = session.execute(
        select(Response.student_id, Response.item_id)
        .join(Item, Item.item_id == Response.item_id)
        .where(Item.strand_id == strand_id)
    ).all()

    return AnsweredOut(
        class_id=str(class_id),
        strand_id=str(strand_id),
        answered=[f"{sid}:{iid}" for sid, iid in rows if sid in enrolled],
    )


@router.get("/{client_batch_id}", response_model=AssessmentOut)
def get_batch(
    client_batch_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> AssessmentOut:
    """Has this batch landed?

    A device that lost the reply can ask before deciding whether to resend.
    """
    batch = session.scalar(
        select(AssessmentBatch).where(AssessmentBatch.client_batch_id == client_batch_id)
    )
    if batch is None or repo.classroom_in_school(
        session, batch.class_id, teacher.school_id
    ) is None:
        raise HTTPException(status_code=404, detail="No such batch")
    return AssessmentOut(
        batch_id=str(batch.batch_id),
        client_batch_id=str(batch.client_batch_id),
        class_id=str(batch.class_id),
        strand_id=str(batch.strand_id),
        responses_recorded=batch.response_count,
        duplicate=True,
        detail="Already recorded.",
    )


assert Student  # imported for the relationship registry
