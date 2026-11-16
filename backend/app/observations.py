"""
Observed evidence: tasks a teacher watches and judges against the KICD rubric.

Added 16 November after supervisor feedback that the system was "too focused
on question answering". The feedback holds against the curriculum itself:
the KICD designs list observation, projects, oral questions and portfolios
beside written tests, and about a third of the Grade 4-6 indicators in the
corpus ask a learner to demonstrate, carry out or make something - which no
multiple-choice question can see.

So a teacher can now record a task the class did (an observation, a project
or a presentation) on one sub-strand, choose one to five indicators for it,
and give each learner a KICD level on each indicator: Exceeds, Meets,
Approaches or Below expectation. Three rules shape it:

  * **Kept apart from the IRT estimate.** A rubric level is a judgement on a
    four-point scale, a theta is a model of right and wrong answers. They are
    shown side by side and never averaged, because a blend of the two would
    mean neither.
  * **The indicators come from the curriculum when it has them.** The KICD
    rubric rows are offered first, ranked by how many words they share with
    the sub-strand's name. Most sub-strands have none - the four assessed
    learning areas carry 176 rubric rows across Grades 4 to 6 - so a teacher
    can write one, and it is kept for that sub-strand at that school.
  * **The support list counts it as its own signal.** Two observed tasks in a
    row on the same sub-strand with the learner below Meets adds them, the
    same "twice, not once" rule the quiz path uses, and the row says which
    kind of evidence put them there.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from . import repository as repo
from .auth import current_teacher
from .db import get_session
from .models import (
    Classroom,
    ClassStrand,
    ObservationTask,
    RubricIndicator,
    RubricScore,
    Strand,
    Student,
    Teacher,
)
from .security import ROLE_SCHOOL_ADMIN, role_at_least

router = APIRouter(prefix="/api", tags=["observations"])

KINDS = ("observation", "project", "presentation")
MAX_INDICATORS = 5

# The KICD four-point scale as KNEC codes it.
LEVELS = {
    4: "Exceeds expectation",
    3: "Meets expectation",
    2: "Approaches expectation",
    1: "Below expectation",
}
# A learner's level on a task is the mean of their levels on its indicators.
# Below this they are short of Meets on that task.
MEETS = 2.5
CONSECUTIVE_FOR_FLAG = 2


def tier_for_mean(mean: float) -> str:
    """The KICD level a mean of indicator levels rounds to (halves round up)."""
    if mean >= 3.5:
        return LEVELS[4]
    if mean >= MEETS:
        return LEVELS[3]
    if mean >= 1.5:
        return LEVELS[2]
    return LEVELS[1]


# --- ranking the curriculum's indicators against a sub-strand ---------------
_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(
    "ability learner learners using their with from that this different various "
    "appropriate correctly given other which ways about into them they have been "
    "what when where some also each such both more most very well will".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def terms(text: str | None) -> set[str]:
    """Content words, crudely stemmed, so "demonstrating" meets "demonstrate"."""
    return {
        _stem(w) for w in _WORD.findall((text or "").lower())
        if len(w) >= 4 and w not in _STOP
    }


def relevance(strand_name: str, indicator: str) -> int:
    """Shared words, the sub-strand's counting double.

    "3.0 Force and Energy / 3.3 Heat Transfer" against "Demonstrating the
    modes of heat transfer in nature" scores 4. Lexical on purpose: the list
    is short (8 to 40 rows for one grade and learning area), the teacher sees
    all of it, and a ranking they can predict beats one they cannot.
    """
    strand, _, sub = strand_name.rpartition(" / ")
    words = terms(indicator)
    return 2 * len(words & terms(sub)) + len(words & terms(strand))


# --- reading ---------------------------------------------------------------
def indicators_for(
    session: Session, strand: Strand, school_id: uuid.UUID
) -> list[RubricIndicator]:
    """What a task on this sub-strand may be judged against, best match first.

    The school's own indicators for the sub-strand come first, then the KICD
    rows for its grade and learning area by relevance. A strand with no grade
    or learning area (made before the catalogue) gets only the school's own.
    """
    conditions = [
        and_(
            RubricIndicator.source == "teacher",
            RubricIndicator.strand_id == strand.strand_id,
            RubricIndicator.school_id == school_id,
        )
    ]
    if strand.grade and strand.learning_area:
        conditions.append(
            and_(
                RubricIndicator.source == "kicd",
                RubricIndicator.grade == strand.grade,
                RubricIndicator.learning_area == strand.learning_area,
            )
        )
    rows = list(session.scalars(select(RubricIndicator).where(or_(*conditions))))
    return sorted(
        rows,
        key=lambda r: (
            r.source != "teacher",
            -relevance(strand.name, r.indicator),
            r.source_row if r.source_row is not None else -1,
            r.indicator,
        ),
    )


def task_levels(scores: list[RubricScore]) -> dict[uuid.UUID, float]:
    """student_id -> mean level across the task's indicators they were given."""
    by_student: dict[uuid.UUID, list[int]] = defaultdict(list)
    for s in scores:
        by_student[s.student_id].append(s.level)
    return {sid: sum(v) / len(v) for sid, v in by_student.items()}


def learner_observations(
    session: Session, student_id: uuid.UUID, strand_id: uuid.UUID | None = None
) -> list[dict]:
    """Every level recorded for a learner, newest task first.

    Plain dicts, because the report prompt reads them as well as the API.
    """
    stmt = (
        select(RubricScore, ObservationTask, RubricIndicator, Strand)
        .join(ObservationTask, ObservationTask.task_id == RubricScore.task_id)
        .join(RubricIndicator, RubricIndicator.indicator_id == RubricScore.indicator_id)
        .join(Strand, Strand.strand_id == ObservationTask.strand_id)
        .where(RubricScore.student_id == student_id)
    )
    if strand_id is not None:
        stmt = stmt.where(ObservationTask.strand_id == strand_id)
    out = []
    for score, task, indicator, strand in session.execute(stmt).all():
        key = str(indicator.indicator_id)
        order = task.indicator_ids.index(key) if key in task.indicator_ids else 99
        out.append(
            {
                "task_id": str(task.task_id),
                "title": task.title,
                "kind": task.kind,
                "strand_id": str(strand.strand_id),
                "strand": strand.name,
                "observed_at": task.created_at,
                "indicator": indicator.indicator,
                "source": indicator.source,
                "level": score.level,
                "tier": LEVELS[score.level],
                "note": score.note,
                "_order": order,
            }
        )
    # Within one task, the indicators in the order the teacher chose them;
    # the second sort is stable, so it keeps that order inside each task.
    out.sort(key=lambda o: o["_order"])
    out.sort(key=lambda o: (o["observed_at"] or datetime.min, o["task_id"]), reverse=True)
    for o in out:
        del o["_order"]
    return out


def observation_flags(
    session: Session, school_id: uuid.UUID, strand_id: uuid.UUID | None = None
) -> list[dict]:
    """Learners short of Meets on their last two observed tasks on a sub-strand.

    Computed when asked rather than stored as a GapFlag. The quiz flag is
    stored because it is raised by an event, recording levels; an observed
    level can be corrected at any time by saving the grid again, and a stored
    flag would then be wrong until something cleared it.
    """
    stmt = (
        select(RubricScore, ObservationTask)
        .join(ObservationTask, ObservationTask.task_id == RubricScore.task_id)
        .join(Classroom, Classroom.class_id == ObservationTask.class_id)
        .join(Student, Student.student_id == RubricScore.student_id)
        .where(Classroom.school_id == school_id, Student.is_active.is_(True))
    )
    if strand_id is not None:
        stmt = stmt.where(ObservationTask.strand_id == strand_id)

    tasks: dict[uuid.UUID, ObservationTask] = {}
    scores: dict[tuple[uuid.UUID, uuid.UUID], list[RubricScore]] = defaultdict(list)
    for score, task in session.execute(stmt).all():
        tasks[task.task_id] = task
        scores[(score.student_id, task.task_id)].append(score)

    # (student, strand) -> [(when, task, mean)]
    history: dict[tuple[uuid.UUID, uuid.UUID], list] = defaultdict(list)
    for (student_id, task_id), rows in scores.items():
        task = tasks[task_id]
        mean = sum(r.level for r in rows) / len(rows)
        history[(student_id, task.strand_id)].append((task.created_at, task, mean, rows))

    out = []
    for (student_id, strand), entries in history.items():
        entries.sort(key=lambda e: (e[0] or datetime.min, str(e[1].task_id)))
        last = entries[-CONSECUTIVE_FOR_FLAG:]
        if len(last) < CONSECUTIVE_FOR_FLAG or any(m >= MEETS for _, _, m, _ in last):
            continue
        latest_when, latest_task, latest_mean, latest_rows = last[-1]
        out.append(
            {
                "student_id": student_id,
                "strand_id": strand,
                "class_id": latest_task.class_id,
                "severity": tier_for_mean(latest_mean),
                "flagged_at": max(
                    (r.recorded_at for r in latest_rows if r.recorded_at),
                    default=latest_when,
                ),
                "tasks": [t.title for _, t, _, _ in last],
            }
        )
    return out


# --- the API ---------------------------------------------------------------
class IndicatorOut(BaseModel):
    indicator_id: str
    indicator: str
    exceeds: str | None
    meets: str | None
    approaches: str | None
    below: str | None
    source: str
    # Shares words with the sub-strand's name. The page lists these first
    # and says so; the rest are the same grade and learning area.
    suggested: bool = False


class IndicatorIn(BaseModel):
    indicator: str = Field(min_length=5, max_length=300)
    exceeds: str | None = Field(default=None, max_length=400)
    meets: str | None = Field(default=None, max_length=400)
    approaches: str | None = Field(default=None, max_length=400)
    below: str | None = Field(default=None, max_length=400)

    @field_validator("indicator")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 5:
            raise ValueError("Write the indicator in a few words")
        return value


class TaskIn(BaseModel):
    strand_id: uuid.UUID
    kind: Literal["observation", "project", "presentation"]
    title: str = Field(min_length=1, max_length=200)
    indicator_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_INDICATORS)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the task a name")
        return value


class ScoreIn(BaseModel):
    student_id: uuid.UUID
    indicator_id: uuid.UUID
    # None clears a level given by mistake.
    level: int | None = Field(default=None, ge=1, le=4)
    note: str | None = Field(default=None, max_length=500)


class ScoresIn(BaseModel):
    scores: list[ScoreIn] = Field(max_length=2000)


class ScoreOut(BaseModel):
    student_id: str
    indicator_id: str
    level: int
    note: str | None


class LearnerOut(BaseModel):
    student_id: str
    name: str


class TaskSummaryOut(BaseModel):
    task_id: str
    strand_id: str
    strand: str
    kind: str
    title: str
    created_at: str | None
    indicators: int
    learners_observed: int
    # Learners at each KICD level on this task, by the mean of their levels.
    levels: dict[str, int]


class TaskOut(BaseModel):
    task_id: str
    class_id: str
    strand_id: str
    strand: str
    kind: str
    title: str
    created_at: str | None
    indicators: list[IndicatorOut]
    learners: list[LearnerOut]
    scores: list[ScoreOut]


class LearnerObservationOut(BaseModel):
    task_id: str
    title: str
    kind: str
    strand_id: str
    strand: str
    observed_at: str | None
    indicator: str
    level: int
    tier: str
    note: str | None


def _indicator_out(r: RubricIndicator, strand: Strand | None = None) -> IndicatorOut:
    return IndicatorOut(
        indicator_id=str(r.indicator_id),
        indicator=r.indicator,
        exceeds=r.exceeds,
        meets=r.meets,
        approaches=r.approaches,
        below=r.below,
        source=r.source,
        suggested=bool(strand) and (
            r.source == "teacher" or relevance(strand.name, r.indicator) > 0
        ),
    )


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _school_strand(session: Session, strand_id: uuid.UUID, school_id: uuid.UUID) -> Strand:
    strand = session.get(Strand, strand_id)
    if strand is None or strand_id not in {
        s.strand_id for s in repo.school_strands(session, school_id)
    }:
        raise HTTPException(status_code=404, detail="No such strand at your school")
    return strand


def _task_in_school(session: Session, task_id: uuid.UUID, school_id: uuid.UUID):
    task = session.get(ObservationTask, task_id)
    if task is None or repo.classroom_in_school(session, task.class_id, school_id) is None:
        raise HTTPException(status_code=404, detail="No such observed task")
    return task


def _task_out(session: Session, task: ObservationTask) -> TaskOut:
    strand = session.get(Strand, task.strand_id)
    wanted = [uuid.UUID(i) for i in task.indicator_ids]
    found = {
        r.indicator_id: r
        for r in session.scalars(
            select(RubricIndicator).where(RubricIndicator.indicator_id.in_(wanted))
        )
    }
    scores = session.scalars(
        select(RubricScore).where(RubricScore.task_id == task.task_id)
    ).all()
    return TaskOut(
        task_id=str(task.task_id),
        class_id=str(task.class_id),
        strand_id=str(task.strand_id),
        strand=strand.name if strand else "",
        kind=task.kind,
        title=task.title,
        created_at=_iso(task.created_at),
        indicators=[_indicator_out(found[i]) for i in wanted if i in found],
        learners=[
            LearnerOut(student_id=str(s.student_id), name=s.name)
            for s in repo.classroom_students(session, task.class_id)
        ],
        scores=[
            ScoreOut(
                student_id=str(s.student_id),
                indicator_id=str(s.indicator_id),
                level=s.level,
                note=s.note,
            )
            for s in scores
        ],
    )


@router.get("/strands/{strand_id}/indicators", response_model=list[IndicatorOut])
def list_indicators(
    strand_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[IndicatorOut]:
    strand = _school_strand(session, strand_id, teacher.school_id)
    return [_indicator_out(r, strand) for r in indicators_for(session, strand, teacher.school_id)]


@router.post(
    "/strands/{strand_id}/indicators", response_model=IndicatorOut, status_code=201
)
def write_indicator(
    strand_id: uuid.UUID,
    body: IndicatorIn,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> IndicatorOut:
    """A teacher's own indicator, for a sub-strand the KICD rubric does not cover."""
    strand = _school_strand(session, strand_id, teacher.school_id)
    clean = {
        f: (" ".join(v.split()) or None) if v else None
        for f, v in body.model_dump(exclude={"indicator"}).items()
    }
    row = RubricIndicator(
        source="teacher",
        grade=strand.grade,
        learning_area=strand.learning_area,
        indicator=body.indicator,
        strand_id=strand.strand_id,
        school_id=teacher.school_id,
        created_by=teacher.teacher_id,
        **clean,
    )
    session.add(row)
    session.commit()
    return _indicator_out(row, strand)


@router.post(
    "/classrooms/{class_id}/observations", response_model=TaskOut, status_code=201
)
def create_task(
    class_id: uuid.UUID,
    body: TaskIn,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> TaskOut:
    classroom = repo.classroom_in_school(session, class_id, teacher.school_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    if session.get(ClassStrand, (class_id, body.strand_id)) is None:
        raise HTTPException(status_code=404, detail="This class is not assessed on that strand")
    strand = session.get(Strand, body.strand_id)

    chosen = list(dict.fromkeys(body.indicator_ids))  # drop repeats, keep order
    allowed = {r.indicator_id for r in indicators_for(session, strand, teacher.school_id)}
    if any(i not in allowed for i in chosen):
        raise HTTPException(
            status_code=422,
            detail="An indicator chosen is not one offered for this strand",
        )
    task = ObservationTask(
        class_id=class_id,
        strand_id=body.strand_id,
        kind=body.kind,
        title=body.title,
        indicator_ids=[str(i) for i in chosen],
        created_by=teacher.teacher_id,
    )
    session.add(task)
    session.commit()
    return _task_out(session, task)


@router.get("/classrooms/{class_id}/observations", response_model=list[TaskSummaryOut])
def list_tasks(
    class_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[TaskSummaryOut]:
    """The class's observed tasks, newest first, each with how the class did."""
    if repo.classroom_in_school(session, class_id, teacher.school_id) is None:
        raise HTTPException(status_code=404, detail="No such classroom")
    tasks = session.scalars(
        select(ObservationTask)
        .where(ObservationTask.class_id == class_id)
        .order_by(ObservationTask.created_at.desc(), ObservationTask.task_id)
    ).all()
    active = {s.student_id for s in repo.classroom_students(session, class_id)}
    out = []
    for task in tasks:
        strand = session.get(Strand, task.strand_id)
        scores = session.scalars(
            select(RubricScore).where(RubricScore.task_id == task.task_id)
        ).all()
        means = {k: v for k, v in task_levels(list(scores)).items() if k in active}
        levels = {name: 0 for name in LEVELS.values()}
        for mean in means.values():
            levels[tier_for_mean(mean)] += 1
        out.append(
            TaskSummaryOut(
                task_id=str(task.task_id),
                strand_id=str(task.strand_id),
                strand=strand.name if strand else "",
                kind=task.kind,
                title=task.title,
                created_at=_iso(task.created_at),
                indicators=len(task.indicator_ids),
                learners_observed=len(means),
                levels=levels,
            )
        )
    return out


@router.get("/observations/{task_id}", response_model=TaskOut)
def get_task(
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> TaskOut:
    return _task_out(session, _task_in_school(session, task_id, teacher.school_id))


@router.put("/observations/{task_id}/scores", response_model=TaskOut)
def save_scores(
    task_id: uuid.UUID,
    body: ScoresIn,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> TaskOut:
    """Set, change or clear levels. Sending the same grid twice changes nothing.

    All or nothing: one learner who is not in the class, or one indicator the
    task does not use, refuses the whole save, so the grid on the screen and
    the record never disagree about what was kept.
    """
    task = _task_in_school(session, task_id, teacher.school_id)
    learners = {s.student_id for s in repo.classroom_students(session, task.class_id)}
    indicators = {uuid.UUID(i) for i in task.indicator_ids}
    for s in body.scores:
        if s.student_id not in learners:
            raise HTTPException(status_code=422, detail="A learner is not in this class")
        if s.indicator_id not in indicators:
            raise HTTPException(status_code=422, detail="An indicator is not part of this task")

    existing = {
        (r.student_id, r.indicator_id): r
        for r in session.scalars(select(RubricScore).where(RubricScore.task_id == task_id))
    }
    for s in body.scores:
        current = existing.get((s.student_id, s.indicator_id))
        note = " ".join(s.note.split()) if s.note else None
        if s.level is None:
            if current is not None:
                session.delete(current)
                existing.pop((s.student_id, s.indicator_id))
            continue
        if current is None:
            current = RubricScore(
                task_id=task_id, student_id=s.student_id, indicator_id=s.indicator_id,
                level=s.level, note=note, recorded_by=teacher.teacher_id,
            )
            session.add(current)
            existing[(s.student_id, s.indicator_id)] = current
        elif current.level != s.level or current.note != note:
            current.level = s.level
            current.note = note
            current.recorded_by = teacher.teacher_id
    session.commit()
    return _task_out(session, task)


@router.delete("/observations/{task_id}", status_code=204)
def delete_task(
    task_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> Response:
    """Removes a task made by mistake, with its levels. Its maker or a head teacher."""
    task = _task_in_school(session, task_id, teacher.school_id)
    if task.created_by != teacher.teacher_id and not role_at_least(
        teacher.role, ROLE_SCHOOL_ADMIN
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the teacher who made this task or a head teacher can remove it",
        )
    session.execute(delete(RubricScore).where(RubricScore.task_id == task_id))
    session.delete(task)
    session.commit()
    return Response(status_code=204)


@router.get(
    "/students/{student_id}/observations", response_model=list[LearnerObservationOut]
)
def learner_levels(
    student_id: uuid.UUID,
    session: Session = Depends(get_session),
    teacher: Teacher = Depends(current_teacher),
) -> list[LearnerObservationOut]:
    if repo.student_in_school(session, student_id, teacher.school_id) is None:
        raise HTTPException(status_code=404, detail="No such learner")
    return [
        LearnerObservationOut(
            **{k: v for k, v in o.items() if k not in ("observed_at", "source")},
            observed_at=_iso(o["observed_at"]),
        )
        for o in learner_observations(session, student_id)
    ]
