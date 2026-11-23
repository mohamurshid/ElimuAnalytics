"""
The practice-set demonstration step, run against the real seed.

It must leave the kept-back learner able to get a practice set, touch only
the demonstration class, and change nothing when run a second time.
"""

from __future__ import annotations

import pytest
from app.demo_practice import DEMO_BANK, KEEP_FOR_PRACTICE, run
from app.models import Base, Item, Response, Student
from app.practice import Calibrated, choose_practice
from app.seed import seed
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from .test_repository import PORTABLE_TABLES


@pytest.fixture
def seeded() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=PORTABLE_TABLES)
    with Session(engine) as s:
        seed(s)
        yield s


def test_half_the_class_answers_and_the_kept_learner_can_practise(seeded):
    result = run(seeded)
    assert result["added"] == len(DEMO_BANK)
    assert 15 <= result["answered_by"] <= 20
    new = list(seeded.scalars(select(Item).where(Item.question_text.in_(
        [q for q, *_ in DEMO_BANK]))))
    assert all(i.difficulty_b is not None and i.discrimination_a is not None for i in new)

    chebet = seeded.scalar(select(Student).where(Student.name == KEEP_FOR_PRACTICE))
    answered = seeded.scalar(select(func.count()).select_from(Response).where(
        Response.student_id == chebet.student_id,
        Response.item_id.in_([i.item_id for i in new])))
    assert answered == 0
    chosen = choose_practice(-1.7, [Calibrated(str(i.item_id), i.difficulty_b,
                                               i.discrimination_a) for i in new])
    assert len(chosen) == 5


def test_running_it_again_changes_nothing(seeded):
    run(seeded)
    before = seeded.scalar(select(func.count()).select_from(Response))
    assert run(seeded)["added"] == 0
    assert seeded.scalar(select(func.count()).select_from(Response)) == before
