"""
What a class is assessed on: list, add from the catalogue, remove.

Any teacher at the school may change this, decided 20 October. Choosing
what to assess is day-to-day teaching, and removing a strand from a class
only removes the link - answers, levels and flags are kept and come back
into view if the strand is added again.

A strand is created the first time any class, at any school, picks its
sub-strand, and reused after that. Strands are shared because the question
bank is: two schools assessing Grade 5 Heat transfer answer the same
questions, and every answer improves the calibration for both.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .catalogue import Entry, Row, catalogue_rows, lookup
from .db import get_session
from .diagnostics import StrandOut, strand_out
from .models import Classroom, ClassStrand, Strand, Teacher

router = APIRouter(prefix="/api", tags=["class strands"])

# Grades 4-6 are the only grades the catalogue offers; KICD calls them Upper
# Primary.
LEVEL = "Upper Primary"


class AddStrand(BaseModel):
    key: str


class RemovalOut(BaseModel):
    removed: bool


def _classroom(session: Session, class_id: uuid.UUID, teacher: Teacher) -> Classroom:
    classroom = repo.classroom_in_school(session, class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    return classroom


def _strand_for(session: Session, entry: Entry) -> Strand:
    """The shared strand for a catalogue entry, made if this is its first use."""
    existing = session.scalar(select(Strand).where(Strand.curriculum_key == entry.key))
    if existing is not None:
        return existing
    strand = Strand(
        name=entry.strand_name,
        level=LEVEL,
        learning_area=entry.learning_area,
        grade=entry.grade,
        curriculum_key=entry.key,
    )
    session.add(strand)
    try:
        session.flush()
    except IntegrityError:
        # Another request created it between the select and the insert.
        session.rollback()
        strand = session.scalar(select(Strand).where(Strand.curriculum_key == entry.key))
        if strand is None:
            raise
    return strand


@router.get("/classrooms/{class_id}/strands", response_model=list[StrandOut])
def list_class_strands(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[StrandOut]:
    _classroom(session, class_id, teacher)
    return [strand_out(session, s) for s in repo.class_strands(session, class_id)]


@router.post("/classrooms/{class_id}/strands", response_model=StrandOut)
def add_class_strand(
    class_id: uuid.UUID,
    body: AddStrand,
    response: Response,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
    rows: list[Row] = Depends(catalogue_rows),
) -> StrandOut:
    """201 when the strand is added; 200 when the class already had it, so a
    double tap on a slow connection is not an error."""
    classroom = _classroom(session, class_id, teacher)
    if not classroom.is_active:
        raise HTTPException(
            status_code=409,
            detail="This class has been withdrawn. Restore it before changing what it is "
            "assessed on.",
        )
    entry = lookup(rows, body.key)
    if entry is None:
        raise HTTPException(
            status_code=422,
            detail="That sub-strand is not in the curriculum catalogue.",
        )

    strand = _strand_for(session, entry)
    link = session.get(ClassStrand, (class_id, strand.strand_id))
    if link is None:
        session.add(ClassStrand(class_id=class_id, strand_id=strand.strand_id))
        response.status_code = 201
    else:
        response.status_code = 200
    session.commit()
    return strand_out(session, strand)


@router.delete("/classrooms/{class_id}/strands/{strand_id}", response_model=RemovalOut)
def remove_class_strand(
    class_id: uuid.UUID,
    strand_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> RemovalOut:
    """Unlinks only. Nothing a learner answered is touched."""
    classroom = _classroom(session, class_id, teacher)
    if not classroom.is_active:
        raise HTTPException(
            status_code=409,
            detail="This class has been withdrawn. Restore it before changing what it is "
            "assessed on.",
        )
    link = session.get(ClassStrand, (class_id, strand_id))
    if link is None:
        raise HTTPException(status_code=404, detail="This class is not assessed on that strand")
    session.delete(link)
    session.commit()
    return RemovalOut(removed=True)
