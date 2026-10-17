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
# Question, options, index of the correct option.
#
# Placeholder content, as the whole demonstration classroom is - but the
# shape is real: four options, one key, and the key never leaves the server.
# Real items come from a teacher through the item bank.
QUESTION_BANK: list[tuple[str, list[str], int]] = [
    ("A metal spoon is left in hot porridge. What happens to the handle?",
     ["It becomes hot", "It stays cool", "It becomes wet", "It changes colour"], 0),
    ("Which keeps hot food warm for longer: a metal tin or a clay pot?",
     ["The metal tin", "The clay pot", "Both the same", "Neither"], 1),
    ("Name one good conductor of heat found in the kitchen.",
     ["A wooden spoon", "A cotton cloth", "An aluminium sufuria", "A plastic bowl"], 2),
    ("Why is the handle of a cooking pot covered with plastic?",
     ["To make it colourful", "Because plastic is cheap",
      "To make the pot heavier", "Because plastic is a poor conductor"], 3),
    ("How does heat reach your hand when you sit near a fire?",
     ["By radiation", "By conduction", "By evaporation", "By condensation"], 0),
    ("Which travels through a metal rod: conduction or radiation?",
     ["Radiation", "Conduction", "Neither", "Both equally"], 1),
    ("Name one poor conductor of heat used to hold hot things.",
     ["Copper wire", "An iron bar", "A dry cloth", "An aluminium sheet"], 2),
    ("Give one safety precaution when handling hot utensils.",
     ["Carry them quickly", "Hold them with bare hands",
      "Pour water on them first", "Use a dry cloth or gloves"], 3),
    ("Why does warm air rise above a cooking fire?",
     ["It is lighter than cold air", "It is heavier than cold air",
      "It is pushed down by smoke", "It does not rise"], 0),
    ("Which mode of heat transfer needs no material to travel through?",
     ["Conduction", "Radiation", "Convection", "All of them"], 1),
    ("Name one material that could be used to make oven gloves.",
     ["Thin polythene", "Aluminium foil", "Thick cotton cloth", "Copper mesh"], 2),
    ("State one use of heat transfer in preserving food.",
     ["Painting the container", "Adding more salt only",
      "Storing food in sunlight", "Boiling milk before storing it"], 3),
]

QUESTIONS = [q for q, _, _ in QUESTION_BANK]
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


def simulated_choices(matrix: np.ndarray) -> np.ndarray:
    """Which option each learner picked, given the correctness matrix.

    A 2-PL model has no concept of WHICH wrong answer a learner chose - it
    yields a probability of being correct and nothing more. So a choice has to
    be invented, and the honest way to invent one is uniformly at random among
    the wrong options.

    That is a deliberate decision, not a shortcut. Picking distractors to form
    a coherent misconception would make the demonstration reliably impressive
    and would mean the system was being shown detecting a pattern that had been
    planted for it to find. With random distractors, a report on seeded data
    correctly reports no single misconception - which demonstrates something
    more useful: that the system declines to invent a pattern when there is
    none. Real patterns come from real learners answering through the quiz,
    where `selected_option` records an actual choice.

    A SEPARATE generator, seeded independently, because `simulated_responses`
    is pinned by the regression that holds Chebet at theta = -1.741 and must
    produce the identical matrix it always has. Drawing choices from the same
    stream would advance it and silently change every ability estimate in the
    demonstration classroom.

    Returns an array shaped like `matrix`; entries for unanswered items are
    left at INVALID_RESPONSE.
    """
    rng = np.random.default_rng(20261017)
    n_items, n_students = matrix.shape
    choices = np.full((n_items, n_students), INVALID_RESPONSE, dtype=int)

    for r, (_question, options, key) in enumerate(QUESTION_BANK):
        wrong = [i for i in range(len(options)) if i != key]
        for c in range(n_students):
            if matrix[r, c] == INVALID_RESPONSE:
                continue
            choices[r, c] = key if matrix[r, c] else wrong[rng.integers(len(wrong))]
    return choices


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
    classroom = Classroom(grade="Grade 5", name="Blue", school=school, teacher=teacher)
    strand = Strand(name=STRAND_NAME, level="Upper Primary")

    items = [
        Item(
            question_text=question,
            options=options,
            correct_option=key,
            strand=strand,
        )
        for question, options, key in QUESTION_BANK
    ]
    students = [
        Student(name=NAMED.get(i, f"Learner {i + 1:02d}"), classroom=classroom)
        for i in range(N_STUDENTS)
    ]

    session.add_all([school, teacher, head, classroom, strand, *items, *students])
    session.flush()  # assign primary keys before responses reference them

    matrix = simulated_responses()
    # Both fields are stored, which mirrors what the quiz path produces: the
    # device sends the option, the server computes correctness from the key and
    # writes both. Seeding only one of them would leave the demonstration
    # classroom unable to exercise the failure-pattern query.
    choices = simulated_choices(matrix)
    responses = [
        Response(
            student_id=students[c].student_id,
            item_id=items[r].item_id,
            correctness=bool(matrix[r, c]),
            selected_option=int(choices[r, c]),
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
