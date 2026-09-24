"""
Create the schema and seed a demonstration classroom.

The seeded data reproduces the Phase 1 skeleton exactly - same twelve Heat
Transfer items, same forty learners, same three named students, same underlying
abilities - so the walking skeleton behaves identically once it is reading from
PostgreSQL instead of an in-memory array. If the numbers change when the
database arrives, something is wrong with the database, not with the model.

    python -m app.seed            create schema and seed
    python -m app.seed --reset    drop everything first
"""

from __future__ import annotations

import argparse

import numpy as np
from girth import INVALID_RESPONSE
from sqlalchemy.orm import Session

from .db import ensure_extensions, get_engine, get_session_factory
from .models import (
    Base,
    Classroom,
    Item,
    Response,
    School,
    Strand,
    Student,
    Teacher,
)
from .security import ROLE_SCHOOL_ADMIN, hash_password

STRAND_NAME = "3.0 Force and Energy / 3.3 Heat Transfer"
QUESTIONS = [
    "A metal spoon is left in hot porridge. What happens to the handle?",
    "Which keeps hot food warm for longer: a metal tin or a clay pot?",
    "Name one good conductor of heat found in the kitchen.",
    "Why is the handle of a cooking pot covered with plastic?",
    "How does heat reach your hand when you sit near a fire?",
    "Which travels through a metal rod: conduction or radiation?",
    "Name one poor conductor of heat used to hold hot things.",
    "Give one safety precaution when handling hot utensils.",
    "Why does warm air rise above a cooking fire?",
    "Which mode of heat transfer needs no material to travel through?",
    "Name one material that could be used to make oven gloves.",
    "State one use of heat transfer in preserving food.",
]
N_STUDENTS = 40
NAMED = {0: "Chebet K.", 1: "Amina W.", 2: "Otieno J."}


def simulated_responses() -> np.ndarray:
    """Identical to the Phase 1 skeleton: same seed, same true abilities."""
    rng = np.random.default_rng(169962)
    n_items = len(QUESTIONS)

    difficulty = rng.normal(0.0, 1.0, n_items)
    discrimination = rng.uniform(0.8, 2.0, n_items)
    theta = rng.normal(0.0, 1.0, N_STUDENTS)
    theta[0] = -1.8
    theta[1] = 0.4
    theta[2] = -0.5

    p = 1.0 / (
        1.0 + np.exp(-discrimination[:, None] * (theta[None, :] - difficulty[:, None]))
    )
    responses = (rng.random((n_items, N_STUDENTS)) < p).astype(int)
    responses[3:, 2] = INVALID_RESPONSE  # Otieno answered only three items
    return responses


def seed(session: Session) -> None:
    if session.query(School).count():
        print("Database already seeded; nothing to do.")
        return

    school = School(name="Demonstration Primary School", type="public")
    # Demonstration accounts. The password is printed below rather than hidden,
    # because a seeded credential that nobody can find is not a secret, it is a
    # support ticket. Change or remove these before any real deployment.
    teacher = Teacher(
        name="Demo Teacher",
        email="teacher@example.school",
        password_hash=hash_password("elimu-demo"),
        role="teacher",
        school=school,
    )
    head = Teacher(
        name="Demo Head Teacher",
        email="head@example.school",
        password_hash=hash_password("elimu-demo"),
        role=ROLE_SCHOOL_ADMIN,
        school=school,
    )
    classroom = Classroom(grade="Grade 5", school=school, teacher=teacher)
    strand = Strand(name=STRAND_NAME, level="Upper Primary")

    items = [Item(question_text=q, strand=strand) for q in QUESTIONS]
    students = [
        Student(name=NAMED.get(i, f"Learner {i + 1:02d}"), classroom=classroom)
        for i in range(N_STUDENTS)
    ]

    session.add_all([school, teacher, head, classroom, strand, *items, *students])
    session.flush()  # assign primary keys before responses reference them

    matrix = simulated_responses()
    responses = [
        Response(
            student_id=students[c].student_id,
            item_id=items[r].item_id,
            correctness=bool(matrix[r, c]),
        )
        for r in range(matrix.shape[0])
        for c in range(matrix.shape[1])
        if matrix[r, c] != INVALID_RESPONSE  # unanswered items are absent rows
    ]
    session.add_all(responses)
    session.commit()

    print(f"seeded: 1 school, 2 teacher accounts, 1 classroom, 1 strand, "
          f"{len(items)} items, {len(students)} students, {len(responses)} responses")
    print()
    print("  teacher@example.school / elimu-demo   (role: teacher)")
    print("  head@example.school    / elimu-demo   (role: school_admin)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables first")
    args = ap.parse_args()

    ensure_extensions()
    if args.reset:
        Base.metadata.drop_all(get_engine())
        print("dropped all tables")
    Base.metadata.create_all(get_engine())
    print("schema created")

    with get_session_factory()() as session:
        seed(session)


if __name__ == "__main__":
    main()
