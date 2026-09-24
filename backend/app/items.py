"""
Item bank CRUD.

Access follows the roles in Chapter 3: any authenticated teacher may read the
bank and author items for their own teaching, while withdrawing an item is a
school-administrator action because it changes what every future calibration in
that strand is computed from.

Deletion has a safeguard. An item that learners have already answered is never
destroyed - the foreign key would cascade and take those responses with it,
silently changing every ability estimate ever derived from them. Such an item is
deactivated instead: withdrawn from future calibration, its history intact.
Only an item nobody has answered can be deleted outright.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_teacher, require_school_admin
from .db import get_session
from .models import Item, Response, Strand, Teacher

router = APIRouter(prefix="/api/items", tags=["item bank"])


class ItemCreate(BaseModel):
    strand_id: uuid.UUID
    question_text: str = Field(min_length=5, max_length=2000)


class ItemUpdate(BaseModel):
    question_text: str | None = Field(default=None, min_length=5, max_length=2000)
    is_active: bool | None = None


class ItemOut(BaseModel):
    item_id: str
    strand_id: str
    question_text: str
    difficulty_b: float | None
    discrimination_a: float | None
    is_active: bool
    response_count: int


def _to_out(item: Item, response_count: int) -> ItemOut:
    return ItemOut(
        item_id=str(item.item_id),
        strand_id=str(item.strand_id),
        question_text=item.question_text,
        difficulty_b=item.difficulty_b,
        discrimination_a=item.discrimination_a,
        is_active=item.is_active,
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


@router.get("", response_model=list[ItemOut])
def list_items(
    strand_id: uuid.UUID | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> list[ItemOut]:
    stmt = select(Item).order_by(Item.item_id)
    if strand_id:
        stmt = stmt.where(Item.strand_id == strand_id)
    if not include_inactive:
        stmt = stmt.where(Item.is_active.is_(True))
    items = list(session.scalars(stmt))
    counts = _response_counts(session, [i.item_id for i in items])
    return [_to_out(i, counts.get(i.item_id, 0)) for i in items]


@router.post("", response_model=ItemOut, status_code=201)
def create_item(
    body: ItemCreate,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> ItemOut:
    if session.get(Strand, body.strand_id) is None:
        raise HTTPException(status_code=404, detail="No such strand")
    item = Item(strand_id=body.strand_id, question_text=body.question_text)
    session.add(item)
    session.commit()
    return _to_out(item, 0)


@router.get("/{item_id}", response_model=ItemOut)
def get_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> ItemOut:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")
    return _to_out(item, _response_counts(session, [item_id]).get(item_id, 0))


@router.patch("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: uuid.UUID,
    body: ItemUpdate,
    session: Session = Depends(get_session),
    _: Teacher = Depends(current_teacher),
) -> ItemOut:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")

    counts = _response_counts(session, [item_id])
    answered = counts.get(item_id, 0)

    if body.question_text is not None:
        if answered:
            # Editing the wording of an answered item makes its existing
            # responses answers to a question that no longer exists.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{answered} learner response(s) already recorded against this "
                    "item. Deactivate it and create a replacement rather than "
                    "rewriting a question that has already been answered."
                ),
            )
        item.question_text = body.question_text

    if body.is_active is not None:
        item.is_active = body.is_active

    session.commit()
    return _to_out(item, answered)


@router.delete("/{item_id}", status_code=200)
def delete_item(
    item_id: uuid.UUID,
    session: Session = Depends(get_session),
    _: Teacher = Depends(require_school_admin),
) -> dict:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")

    answered = _response_counts(session, [item_id]).get(item_id, 0)
    if answered:
        item.is_active = False
        session.commit()
        return {
            "deleted": False,
            "deactivated": True,
            "item_id": str(item_id),
            "response_count": answered,
            "detail": (
                f"Item has {answered} learner response(s) and was deactivated "
                "rather than deleted. Deleting it would remove those responses "
                "and change every ability estimate derived from them."
            ),
        }

    session.delete(item)
    session.commit()
    return {"deleted": True, "deactivated": False, "item_id": str(item_id)}
