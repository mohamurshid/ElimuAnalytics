"""
The question bank: reading, writing, and moving a question through review.

Statuses and what each permits are in item_status.py. Who may do what,
agreed 20 October:

  * any teacher may create a question, edit one nobody has answered, approve
    or reject an AI draft, and report an approved question with a reason
  * only a head teacher may resolve a report (approve it again, or retire
    it), retire a question, edit a question learners have answered, or
    delete. Each of these changes what counts toward learners' levels, and
    the bank is shared across schools

**Editing an answered question makes a new version.** The learners'
answers were to the old wording, so the old row keeps them and is retired,
and the edit becomes version n+1, uncalibrated, pointing back to it. An
unanswered question is simply edited.

Nothing here deletes a question anyone has answered: the foreign key would
cascade and take their responses with it, silently changing every ability
estimate ever derived from them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_teacher, require_school_admin
from .db import get_session
from .item_status import (
    APPROVED,
    DRAFT,
    REJECTED,
    REPORTED,
    RETIRED,
    STATUSES,
    TEACHER,
    mcq_problems,
)
from .models import Item, Response, Strand, Teacher
from .security import ROLE_SCHOOL_ADMIN, role_at_least

router = APIRouter(prefix="/api/items", tags=["item bank"])

Text = Field(min_length=5, max_length=2000)


class ItemCreate(BaseModel):
    strand_id: uuid.UUID
    question_text: str = Text
    options: list[str] | None = None
    correct_option: int | None = None
    rationale: str | None = Field(default=None, max_length=1000)
    misconceptions: list[str | None] | None = None


class ItemUpdate(BaseModel):
    question_text: str | None = Field(default=None, min_length=5, max_length=2000)
    options: list[str] | None = None
    correct_option: int | None = None
    rationale: str | None = Field(default=None, max_length=1000)
    misconceptions: list[str | None] | None = None


class ReportBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class ItemOut(BaseModel):
    """The teacher's view of a question, key and mark scheme included.

    Never sent to a learner's device: the quiz endpoint in assessments.py has
    its own schema with neither the key nor the misconceptions.
    """

    item_id: str
    strand_id: str
    question_text: str
    options: list[str] | None
    correct_option: int | None
    rationale: str | None
    misconceptions: list[str | None] | None
    curriculum_excerpt: str | None
    status: str
    source: str
    version: int
    previous_item_id: str | None
    report_reason: str | None
    difficulty_b: float | None
    discrimination_a: float | None
    response_count: int


def _to_out(item: Item, response_count: int) -> ItemOut:
    return ItemOut(
        item_id=str(item.item_id),
        strand_id=str(item.strand_id),
        question_text=item.question_text,
        options=item.options,
        correct_option=item.correct_option,
        rationale=item.rationale,
        misconceptions=item.misconceptions,
        curriculum_excerpt=item.curriculum_excerpt,
        status=item.status,
        source=item.source,
        version=item.version,
        previous_item_id=str(item.previous_item_id) if item.previous_item_id else None,
        report_reason=item.report_reason,
        difficulty_b=item.difficulty_b,
        discrimination_a=item.discrimination_a,
        response_count=response_count,
    )


def _response_counts(session: Session, item_ids: list[uuid.UUID]) -> dict:
    if not item_ids:
        return {}
    rows = session.execute(
        select(Response.item_id, func.count(Response.response_id))
        .where(Response.item_id.in_(item_ids))
        .group_by(Response.item_id)
    ).all()
    return dict(rows)


def _answered(session: Session, item: Item) -> int:
    return _response_counts(session, [item.item_id]).get(item.item_id, 0)


def _get(session: Session, item_id: uuid.UUID) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")
    return item


def _require_head(teacher: Teacher, doing: str) -> None:
    if not role_at_least(teacher.role, ROLE_SCHOOL_ADMIN):
        raise HTTPException(
            status_code=403,
            detail=f"Only a head teacher can {doing}. Any teacher can report a "
            "question, which takes it out of new quizzes straight away.",
        )


def _check_mcq(options, correct_option, misconceptions) -> None:
    problems = mcq_problems(options, correct_option, misconceptions)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _wrong_state(item: Item, action: str) -> HTTPException:
    return HTTPException(
        status_code=409, detail=f"A question that is {item.status} cannot be {action}."
    )


# --- reading ---------------------------------------------------------------
@router.get("", response_model=list[ItemOut])
def list_items(
    strand_id: uuid.UUID | None = Query(default=None),
    status: list[str] = Query(default=[APPROVED]),
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> list[ItemOut]:
    """Approved questions unless other statuses are asked for by name."""
    unknown = sorted(set(status) - set(STATUSES))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown status: {', '.join(unknown)}")
    stmt = select(Item).where(Item.status.in_(status)).order_by(Item.item_id)
    if strand_id:
        stmt = stmt.where(Item.strand_id == strand_id)
    items = list(session.scalars(stmt))
    counts = _response_counts(session, [i.item_id for i in items])
    return [_to_out(i, counts.get(i.item_id, 0)) for i in items]


@router.get("/{item_id}", response_model=ItemOut)
def get_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> ItemOut:
    item = _get(session, item_id)
    return _to_out(item, _answered(session, item))


# --- writing ---------------------------------------------------------------
@router.post("", response_model=ItemOut, status_code=201)
def create_item(
    body: ItemCreate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ItemOut:
    """A teacher's own question is approved as written: its author is its
    reviewer. AI drafts are made by generation, not here."""
    if session.get(Strand, body.strand_id) is None:
        raise HTTPException(status_code=404, detail="No such strand")
    _check_mcq(body.options, body.correct_option, body.misconceptions)
    item = Item(
        strand_id=body.strand_id,
        question_text=body.question_text,
        options=body.options,
        correct_option=body.correct_option,
        rationale=body.rationale,
        misconceptions=body.misconceptions,
        status=APPROVED,
        source=TEACHER,
        created_by=teacher.teacher_id,
        reviewed_by=teacher.teacher_id,
        reviewed_at=_now(),
    )
    session.add(item)
    session.commit()
    return _to_out(item, 0)


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ItemOut:
    """Edit in place, or - for a question learners have answered - make a
    new version and retire this one. The response is the question as it now
    stands, so its `item_id` is new when a version was made."""
    item = _get(session, item_id)
    if item.status in (REJECTED, RETIRED):
        raise _wrong_state(item, "edited")
    answered = _answered(session, item)
    if item.status == REPORTED:
        _require_head(teacher, "resolve a reported question")
    if answered:
        _require_head(teacher, "edit a question learners have already answered")

    changes = body.model_dump(exclude_unset=True)
    merged = {
        "question_text": changes.get("question_text", item.question_text),
        "options": changes.get("options", item.options),
        "correct_option": changes.get("correct_option", item.correct_option),
        "rationale": changes.get("rationale", item.rationale),
        "misconceptions": changes.get("misconceptions", item.misconceptions),
    }
    if merged["question_text"] is None:
        raise HTTPException(status_code=422, detail="A question needs its text")
    _check_mcq(merged["options"], merged["correct_option"], merged["misconceptions"])

    # Editing a reported question is how a head teacher fixes it, so the
    # result is approved. A draft stays a draft until someone approves it.
    status = APPROVED if item.status == REPORTED else item.status

    if not answered:
        for field, value in merged.items():
            setattr(item, field, value)
        if status != item.status:
            item.status = status
            item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
        session.commit()
        return _to_out(item, 0)

    replacement = Item(
        strand_id=item.strand_id,
        **merged,
        status=APPROVED,
        source=item.source,
        version=item.version + 1,
        previous_item_id=item.item_id,
        curriculum_excerpt=item.curriculum_excerpt,
        curriculum_source_row=item.curriculum_source_row,
        created_by=teacher.teacher_id,
        reviewed_by=teacher.teacher_id,
        reviewed_at=_now(),
    )
    item.status = RETIRED
    item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
    session.add(replacement)
    session.commit()
    return _to_out(replacement, 0)


# --- review ----------------------------------------------------------------
@router.post("/{item_id}/approve", response_model=ItemOut)
def approve_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ItemOut:
    """A draft, by any teacher; a reported question, by a head teacher."""
    item = _get(session, item_id)
    if item.status == REPORTED:
        _require_head(teacher, "resolve a reported question")
    elif item.status != DRAFT:
        raise _wrong_state(item, "approved")
    _check_mcq(item.options, item.correct_option, item.misconceptions)
    item.status = APPROVED
    item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
    session.commit()
    return _to_out(item, _answered(session, item))


@router.post("/{item_id}/reject", response_model=ItemOut)
def reject_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ItemOut:
    """Turn down a draft. Kept, not deleted: the approval rate is measured."""
    item = _get(session, item_id)
    if item.status != DRAFT:
        raise _wrong_state(item, "rejected")
    item.status = REJECTED
    item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
    session.commit()
    return _to_out(item, 0)


@router.post("/{item_id}/report", response_model=ItemOut)
def report_item(
    item_id: uuid.UUID,
    body: ReportBody,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> ItemOut:
    """Any teacher. Out of new quizzes and out of levels at once, until a
    head teacher reviews it; answers already given are kept."""
    item = _get(session, item_id)
    if item.status != APPROVED:
        raise _wrong_state(item, "reported")
    item.status = REPORTED
    item.reported_by, item.reported_at = teacher.teacher_id, _now()
    item.report_reason = body.reason.strip()
    session.commit()
    return _to_out(item, _answered(session, item))


@router.post("/{item_id}/retire", response_model=ItemOut)
def retire_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> ItemOut:
    item = _get(session, item_id)
    if item.status not in (APPROVED, REPORTED):
        raise _wrong_state(item, "retired")
    item.status = RETIRED
    item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
    session.commit()
    return _to_out(item, _answered(session, item))


@router.delete("/{item_id}", status_code=200)
def delete_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> dict:
    item = _get(session, item_id)
    answered = _answered(session, item)
    if answered:
        item.status = RETIRED
        item.reviewed_by, item.reviewed_at = teacher.teacher_id, _now()
        session.commit()
        return {
            "deleted": False,
            "retired": True,
            "item_id": str(item_id),
            "response_count": answered,
            "detail": (
                f"Item has {answered} learner response(s) and was retired "
                "rather than deleted. Deleting it would remove those responses "
                "and change every ability estimate derived from them."
            ),
        }

    session.delete(item)
    session.commit()
    return {"deleted": True, "retired": False, "item_id": str(item_id)}
