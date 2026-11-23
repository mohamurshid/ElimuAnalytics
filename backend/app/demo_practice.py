"""
Demonstration data for practice sets.

In the seeded class every learner has answered every Heat Transfer question,
so a practice set has nothing left to choose from: the honest answer is a
refusal. In a real class new questions arrive all the time - a teacher
approves them, gives a short quiz to part of the class, recalibrates, and the
rest of the class can then be given practice sets. This module does that once
for the demonstration class so the whole loop can be shown:

  1. ten more approved Heat Transfer questions, written for the demonstration;
  2. SIMULATED answers to them from half the class - the same 2-PL model as
     the seed, from each learner's current estimate, with a fixed random seed;
  3. one recalibration of the strand for the class, as Recalibrate does.

The other half, Chebet K. among them, have not answered the new questions, so
each can be given a practice set chosen from their own level.

Only the demonstration school is touched (the seeded teacher account), and
running it twice changes nothing the second time.

    python -m app.demo_practice
"""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import repository as repo
from .calibration import calibrate_strand
from .db import get_session_factory
from .irt import diagnose_all
from .models import AssessmentBatch, Classroom, Item, Response, Strand, Teacher
from .seed import STRAND_KEY

DEMO_TEACHER = "teacher@example.school"
KEEP_FOR_PRACTICE = "Chebet K."

# Question, options, key, the misconception behind each wrong option (None
# for the key). Placeholder content in the shape a reviewed question has.
DEMO_BANK: list[tuple[str, list[str], int, list[str | None]]] = [
    ("Which of these is a good conductor of heat?",
     ["Copper", "Wood", "Rubber", "Paper"], 0,
     [None, "Thinks wood passes heat well because it burns",
      "Confuses rubber's grip with passing heat", "Thinks thin materials conduct"]),
    ("Why do people wear woollen clothes on a cold morning?",
     ["Wool makes heat", "Wool is a poor conductor and keeps body heat in",
      "Wool lets cold air in slowly", "Wool is heavy"], 1,
     ["Thinks clothes produce heat", None,
      "Thinks cold flows in rather than heat flowing out", "Links warmth to weight"]),
    ("A pot of water is heated from below. How does the heat spread through the water?",
     ["By radiation only", "By the water staying still", "By convection currents",
      "By the pot cooling"], 2,
     ["Thinks all heating near a fire is radiation", "Does not know liquids move when heated",
      None, "Reverses the direction of heat flow"]),
    ("Which surface absorbs the most heat from the sun?",
     ["A shiny white surface", "A shiny silver surface", "A clear glass surface",
      "A dull black surface"], 3,
     ["Thinks white absorbs most because it is bright",
      "Thinks shiny surfaces collect heat", "Thinks glass traps all heat", None]),
    ("Heat always moves from ...",
     ["a hotter object to a colder one", "a colder object to a hotter one",
      "a smaller object to a bigger one", "a heavier object to a lighter one"], 0,
     [None, "Thinks 'cold' flows like heat does", "Links heat flow to size",
      "Links heat flow to weight"]),
    ("Why are cooking pots usually made of metal?",
     ["Metal is light", "Metal conducts heat to the food quickly", "Metal is shiny",
      "Metal does not get hot"], 1,
     ["Chooses a property that does not affect cooking", None,
      "Chooses appearance over function", "Thinks metal stays cool"]),
    ("How does the sun's heat reach the earth?",
     ["By conduction through the air", "By convection in space", "By radiation",
      "By the wind"], 2,
     ["Thinks space is filled with air", "Thinks convection works in empty space", None,
      "Thinks wind carries the sun's heat"]),
    ("Which is the best way to keep tea hot for longer?",
     ["Pour it into a metal cup", "Leave it uncovered", "Stir it often",
      "Pour it into a flask"], 3,
     ["Thinks metal holds heat in", "Does not link open tops to heat loss",
      "Thinks stirring adds heat", None]),
    ("Why do the coils at the back of a fridge feel warm?",
     ["Heat is removed from inside and given off outside",
      "The fridge makes cold and pushes it out", "The coils are near a fire",
      "Cold air is heavy"], 0,
     [None, "Thinks cold is made and moved like a substance",
      "Looks for an outside heat source", "Uses a true fact that does not explain it"]),
    ("A learner touches a metal desk and a wooden desk in the same room. "
     "The metal feels colder because ...",
     ["the metal is at a lower temperature", "the metal conducts heat away from the hand faster",
      "wood makes its own heat", "metal attracts cold"], 1,
     ["Thinks touch measures temperature directly", None,
      "Thinks wood produces heat", "Thinks cold is attracted like a magnet"]),
]

# Item parameters the simulated answers are drawn from: easy to hard, and
# reasonably discriminating, so the recalibrated bank covers the class's range.
TRUE_DIFFICULTY = np.linspace(-2.6, 1.0, len(DEMO_BANK))
SEED = 20261123


def run(session: Session) -> dict:
    teacher = session.scalar(select(Teacher).where(Teacher.email == DEMO_TEACHER))
    if teacher is None:
        raise SystemExit("The demonstration school is not seeded (python -m app.seed).")
    strand = session.scalar(select(Strand).where(Strand.curriculum_key == STRAND_KEY))
    classroom = session.scalar(
        select(Classroom).where(Classroom.school_id == teacher.school_id,
                                Classroom.grade == "Grade 5")
    )
    if strand is None or classroom is None:
        raise SystemExit("The demonstration class or its Heat Transfer strand is missing.")

    existing = set(session.scalars(
        select(Item.question_text).where(Item.strand_id == strand.strand_id)
    ))
    if all(q in existing for q, *_ in DEMO_BANK):
        return {"added": 0, "note": "Already added; nothing changed."}

    # Current estimates, from which the simulated answers are drawn.
    matrix, item_ids, student_ids = repo.build_response_matrix(
        session, strand.strand_id, classroom.class_id
    )
    estimates = diagnose_all(matrix, len(item_ids), len(student_ids),
                             params=repo.stored_parameters(session, item_ids))
    learners = repo.classroom_students(session, classroom.class_id)
    theta = {
        sid: (r["theta"] if r["theta"] is not None else 0.0)
        for sid, r in zip(student_ids, estimates, strict=True)
    }

    items = []
    for question, options, key, misconceptions in DEMO_BANK:
        if question in existing:
            continue
        item = Item(strand_id=strand.strand_id, question_text=question, options=options,
                    correct_option=key, misconceptions=misconceptions, status="approved",
                    source="teacher", created_by=teacher.teacher_id,
                    reviewed_by=teacher.teacher_id)
        session.add(item)
        items.append(item)
    session.flush()

    # Half the class answers: every other learner in name order, never the
    # learner kept back to show a practice set.
    ordered = sorted((s for s in learners if s.is_active), key=lambda s: s.name)
    answering = [s for n, s in enumerate(ordered)
                 if n % 2 == 1 and s.name != KEEP_FOR_PRACTICE]

    rng = np.random.default_rng(SEED)
    discrimination = rng.uniform(0.9, 1.6, len(DEMO_BANK))
    batch = AssessmentBatch(client_batch_id=uuid.uuid4(), class_id=classroom.class_id,
                            strand_id=strand.strand_id, teacher_id=teacher.teacher_id,
                            response_count=0)
    session.add(batch)
    session.flush()
    responses = []
    bank_index = {q: n for n, (q, *_rest) in enumerate(DEMO_BANK)}
    for item in items:
        n = bank_index[item.question_text]
        wrong = [i for i in range(len(item.options)) if i != item.correct_option]
        for learner in answering:
            p = 1.0 / (1.0 + np.exp(-discrimination[n]
                                    * (theta.get(learner.student_id, 0.0) - TRUE_DIFFICULTY[n])))
            correct = bool(rng.random() < p)
            choice = item.correct_option if correct else wrong[rng.integers(len(wrong))]
            responses.append(Response(student_id=learner.student_id, item_id=item.item_id,
                                      correctness=correct, selected_option=int(choice),
                                      batch_id=batch.batch_id))
    batch.response_count = len(responses)
    session.add_all(responses)
    session.commit()

    calibration = calibrate_strand(session, strand.strand_id, classroom.class_id)
    return {
        "added": len(items),
        "answered_by": len(answering),
        "responses": len(responses),
        "calibrated": calibration["items_calibrated"],
        "ready_for_practice": [s.name for s in ordered if s not in answering][:6],
    }


def main() -> None:
    with get_session_factory()() as session:
        result = run(session)
    if not result["added"]:
        print(result["note"])
        return
    print(f"Added {result['added']} approved Heat Transfer questions to the demonstration class.")
    print(f"Simulated {result['responses']} answers from {result['answered_by']} learners "
          f"and recalibrated: {result['calibrated']} questions now have a difficulty.")
    print("Learners who can now be given a practice set include: "
          + ", ".join(result["ready_for_practice"]))


if __name__ == "__main__":
    main()
