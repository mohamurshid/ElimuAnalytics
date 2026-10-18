"""
Classroom and learner records.

This is the first part of the system where one school's data could leak to
another, so every lookup is scoped. The rule is school-level: a teacher sees
the classrooms and learners of their own school and nothing else, whatever
identifier they supply. The scoping itself lives in `repository.py` so that it
has one home rather than being re-derived at each endpoint.

Out-of-scope records answer **404, not 403**. A 403 would confirm that the
record exists and merely belongs to someone else, which lets an attacker
enumerate identifiers to learn which are real. 404 discloses nothing.

Deletion carries the same safeguard as the item bank, for the same reason. A
learner who has answered anything is withdrawn, never destroyed: the foreign
key cascades to their responses, and recalibrating a strand without those
responses moves the ability estimates of every other learner who sat those
items. Withdrawn learners leave the calibration pool and keep their history.
A classroom whose learners have answered anything is withdrawn on the same
grounds. Only a record nobody has answered against is deleted outright, and
the response says which happened.

**Withdrawal is reversible, and the reversal is exact.** Withdrawing a
classroom also withdraws its learners, so restoring it has to bring them
back - but only the ones that action took, never a learner a teacher had
already withdrawn on purpose. `Student.withdrawn_with_class` records which,
so the undo reverses what the action did rather than approximating it. An
action that is easy to do and hard to undo is the wrong shape, particularly
behind a button labelled "Remove".
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher, require_school_admin
from .db import get_session
from .models import Classroom, Student, Teacher

router = APIRouter(prefix="/api", tags=["classrooms and learners"])

NOT_FOUND_CLASSROOM = "No such classroom"
NOT_FOUND_STUDENT = "No such learner"


# --- schemas ---------------------------------------------------------------
# The six grades this system covers, spelled exactly as the KICD corpus spells
# them. Report retrieval matches a class's grade against the curriculum's
# grade by equality, so "grade 5" or "Gr 5" would create a class whose reports
# could never find any curriculum - and the failure would surface weeks later,
# at the first report, as a 409 nobody connects to a typo. Validated here
# rather than trusted to the form: the interface offers a picker, but the
# server is what has to be right.
Grade = Literal["Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6"]


class ClassroomCreate(BaseModel):
    grade: Grade = Field(examples=["Grade 5"])
    name: str = Field(default="", max_length=100, examples=["Blue"])


class ClassroomUpdate(BaseModel):
    grade: Grade | None = None
    name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ClassroomOut(BaseModel):
    class_id: str
    grade: str
    name: str
    is_active: bool
    student_count: int


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    class_id: uuid.UUID | None = None
    is_active: bool | None = None


class StudentOut(BaseModel):
    student_id: str
    name: str
    class_id: str
    is_active: bool
    response_count: int


class RemovalOut(BaseModel):
    deleted: bool
    deactivated: bool
    response_count: int
    detail: str


class RestoreOut(BaseModel):
    restored: bool
    learners_restored: int
    detail: str


def _classroom_out(session: Session, classroom: Classroom) -> ClassroomOut:
    return ClassroomOut(
        class_id=str(classroom.class_id),
        grade=classroom.grade,
        name=classroom.name,
        is_active=classroom.is_active,
        student_count=len(repo.classroom_students(session, classroom.class_id)),
    )


def _student_out(session: Session, student: Student) -> StudentOut:
    return StudentOut(
        student_id=str(student.student_id),
        name=student.name,
        class_id=str(student.class_id),
        is_active=student.is_active,
        response_count=repo.student_response_count(session, student.student_id),
    )


def _classroom_or_404(session: Session, class_id: uuid.UUID, teacher: Teacher) -> Classroom:
    classroom = repo.classroom_in_school(session, class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_CLASSROOM)
    return classroom


def _student_or_404(session: Session, student_id: uuid.UUID, teacher: Teacher) -> Student:
    student = repo.student_in_school(session, student_id, teacher.school_id)
    if student is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_STUDENT)
    return student


# --- classrooms ------------------------------------------------------------
@router.get("/classrooms", response_model=list[ClassroomOut])
def list_classrooms(
    include_inactive: bool = Query(default=False),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[ClassroomOut]:
    """Classrooms in the caller's school. Never any other school's."""
    rows = repo.school_classrooms(session, teacher.school_id, include_inactive)
    return [_classroom_out(session, c) for c in rows]


@router.post("/classrooms", response_model=ClassroomOut, status_code=201)
def create_classroom(
    body: ClassroomCreate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> ClassroomOut:
    """Create a classroom in the caller's own school.

    `school_id` is taken from the authenticated account rather than the request
    body. Accepting it from the body would let any administrator create a
    classroom inside someone else's school.
    """
    classroom = Classroom(
        grade=body.grade,
        name=body.name,
        school_id=teacher.school_id,
        teacher_id=teacher.teacher_id,
    )
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return _classroom_out(session, classroom)


@router.patch("/classrooms/{class_id}", response_model=ClassroomOut)
def update_classroom(
    class_id: uuid.UUID,
    body: ClassroomUpdate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> ClassroomOut:
    classroom = _classroom_or_404(session, class_id, teacher)
    if body.grade is not None:
        classroom.grade = body.grade
    if body.name is not None:
        classroom.name = body.name
    if body.is_active is not None:
        reactivating = body.is_active and not classroom.is_active
        classroom.is_active = body.is_active
        if reactivating:
            _restore_learners(session, class_id)
    session.commit()
    session.refresh(classroom)
    return _classroom_out(session, classroom)


def _restore_learners(session: Session, class_id: uuid.UUID) -> int:
    """Reactivate exactly the learners this classroom's withdrawal took."""
    taken = list(
        session.scalars(
            select(Student).where(
                Student.class_id == class_id,
                Student.withdrawn_with_class.is_(True),
            )
        )
    )
    for student in taken:
        student.is_active = True
        student.withdrawn_with_class = False
    return len(taken)


@router.post("/classrooms/{class_id}/restore", response_model=RestoreOut)
def restore_classroom(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> RestoreOut:
    """Undo a withdrawal, including the learners it took with it."""
    classroom = _classroom_or_404(session, class_id, teacher)
    if classroom.is_active:
        return RestoreOut(
            restored=False,
            learners_restored=0,
            detail="This classroom is already active.",
        )
    classroom.is_active = True
    restored = _restore_learners(session, class_id)
    session.commit()
    return RestoreOut(
        restored=True,
        learners_restored=restored,
        detail=(
            f"Classroom restored, with {restored} learner(s) that its "
            "withdrawal had taken. Learners withdrawn individually before "
            "that stay withdrawn."
        ),
    )


@router.delete("/classrooms/{class_id}", response_model=RemovalOut)
def remove_classroom(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> RemovalOut:
    classroom = _classroom_or_404(session, class_id, teacher)
    answered = repo.classroom_response_count(session, class_id)

    if answered:
        classroom.is_active = False
        for student in repo.classroom_students(session, class_id):
            # Marked, not merely deactivated: a restore has to be able to tell
            # these apart from learners withdrawn individually beforehand.
            student.is_active = False
            student.withdrawn_with_class = True
        session.commit()
        return RemovalOut(
            deleted=False,
            deactivated=True,
            response_count=answered,
            detail=(
                "Learners in this classroom have recorded responses, so it was "
                "withdrawn rather than deleted. Deleting it would cascade to "
                "those responses and change ability estimates derived from them."
            ),
        )

    session.delete(classroom)
    session.commit()
    return RemovalOut(
        deleted=True,
        deactivated=False,
        response_count=0,
        detail="No responses were recorded against this classroom, so it was deleted.",
    )


# --- learners --------------------------------------------------------------
@router.get("/classrooms/{class_id}/students", response_model=list[StudentOut])
def list_students(
    class_id: uuid.UUID,
    include_inactive: bool = Query(default=False),
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[StudentOut]:
    _classroom_or_404(session, class_id, teacher)
    rows = repo.classroom_students(session, class_id, include_inactive)
    return [_student_out(session, s) for s in rows]


@router.post("/classrooms/{class_id}/students", response_model=StudentOut, status_code=201)
def enrol_student(
    class_id: uuid.UUID,
    body: StudentCreate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> StudentOut:
    """Enrol a learner. Any teacher at the school may do this; it creates no
    risk to existing measurements, unlike withdrawing one."""
    classroom = _classroom_or_404(session, class_id, teacher)
    if not classroom.is_active:
        raise HTTPException(
            status_code=409,
            detail="This classroom has been withdrawn. Reactivate it before enrolling.",
        )
    student = Student(name=body.name, class_id=class_id)
    session.add(student)
    session.commit()
    session.refresh(student)
    return _student_out(session, student)


@router.get("/students/{student_id}", response_model=StudentOut)
def get_student(
    student_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> StudentOut:
    return _student_out(session, _student_or_404(session, student_id, teacher))


@router.patch("/students/{student_id}", response_model=StudentOut)
def update_student(
    student_id: uuid.UUID,
    body: StudentUpdate,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> StudentOut:
    student = _student_or_404(session, student_id, teacher)
    if body.name is not None:
        student.name = body.name
    if body.class_id is not None:
        # A transfer must land inside the caller's own school, so the
        # destination is scoped exactly as the learner was.
        _classroom_or_404(session, body.class_id, teacher)
        student.class_id = body.class_id
    if body.is_active is not None:
        student.is_active = body.is_active
        if body.is_active:
            # Restored on their own: no longer owed back by a class restore.
            student.withdrawn_with_class = False
    session.commit()
    session.refresh(student)
    return _student_out(session, student)


@router.delete("/students/{student_id}", response_model=RemovalOut)
def remove_student(
    student_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(require_school_admin),
) -> RemovalOut:
    student = _student_or_404(session, student_id, teacher)
    answered = repo.student_response_count(session, student_id)

    if answered:
        student.is_active = False
        student.withdrawn_with_class = False  # a deliberate, individual act
        session.commit()
        return RemovalOut(
            deleted=False,
            deactivated=True,
            response_count=answered,
            detail=(
                "This learner has recorded responses, so they were withdrawn "
                "rather than deleted. Deleting them would cascade to those "
                "responses and change every other learner's ability estimate "
                "in the strands they sat."
            ),
        )

    session.delete(student)
    session.commit()
    return RemovalOut(
        deleted=True,
        deactivated=False,
        response_count=0,
        detail="This learner answered nothing, so the record was deleted.",
    )
