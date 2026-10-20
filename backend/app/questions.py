"""
Writing draft questions: the prompt, the shape the model must answer in,
and the checks every question has to pass before a teacher sees it.

Pure - no database, no network - so every rule here is unit-tested, and
the measurement spike for checkpoint 6 can import exactly what production
runs, as the Day 5 spike does for reports.

**Written from the sub-strand's own text.** Reports retrieve curriculum by
similarity because a report starts from a learner. A question starts from a
sub-strand the teacher already chose, so the prompt carries exactly the
corpus rows the catalogue places under it.

**Checks the server makes, because the model is not trusted to:**

  * a well-formed multiple-choice question: four distinct options, one key
    that is one of them, a misconception for each wrong option and none for
    the key (item_status.mcq_problems)
  * the question does not contain its own answer
  * the curriculum excerpt it cites is really in the curriculum text - the
    same grounding idea as reports, checked the same strict way
  * not a near-duplicate of a question already in the bank, or of another in
    the same run (checked in generation.py, which has the embedder)

A question that fails is dropped and recorded with its reasons on the run,
never shown, never silently repaired.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .item_status import mcq_problems

OPTIONS = 4
MAX_EXCERPT_WORDS = 40  # asked for 25; the slack is for counting differences
MAX_EXISTING_IN_PROMPT = 40

# The shape of the model's answer, enforced by the API's structured output.
# Lengths are not expressible here and are checked after, by mcq_problems.
SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    # Each option carries its own misconception. The first
                    # version asked for a separate list aligned by position,
                    # and the model listed the empty entry first and then the
                    # wrong options in order, whatever the key's position -
                    # live run, 20 October. Pairing them removes the alignment.
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "misconception": {"type": "string"},
                            },
                            "required": ["text", "misconception"],
                            "additionalProperties": False,
                        },
                    },
                    "correct_option": {"type": "integer"},
                    "rationale": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
                "required": ["question", "options", "correct_option", "rationale", "excerpt"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SubStrand:
    """What the prompt needs to know about where the questions belong."""

    grade: str
    learning_area: str
    strand: str
    number: str
    name: str
    language: str


def build_prompt(
    sub: SubStrand,
    chunk_texts: Sequence[str],
    count: int,
    existing: Sequence[str] = (),
) -> str:
    curriculum = "\n\n".join(chunk_texts)
    language = "Kiswahili sanifu" if sub.language == "Kiswahili" else "clear, simple English"
    if existing:
        shown = list(existing)[-MAX_EXISTING_IN_PROMPT:]
        existing_block = (
            "\nThese questions are already in the bank. Do not repeat them or "
            "write close paraphrases of them:\n" + "\n".join(f"- {q}" for q in shown) + "\n"
        )
    else:
        existing_block = ""

    return f"""You are writing multiple-choice questions for {sub.grade} learners in Kenya, \
for the Competency-Based Education curriculum.

SUB-STRAND: {sub.strand} / {sub.number} {sub.name} ({sub.learning_area}, {sub.grade})

CURRICULUM TEXT (from the official KICD {sub.grade} curriculum design):
{curriculum}

Write {count} questions that assess this sub-strand's specific learning outcomes, \
using only what the curriculum text above covers.

Every question:
- Is written in {language}, at a reading level a {sub.grade} learner can manage. One \
short sentence where possible.
- Has exactly {OPTIONS} options, with exactly one correct answer, and all {OPTIONS} \
options about the same length.
- Has wrong options that are each believable to a learner who holds a specific, common \
misconception about this topic. No joke options, and no "all of the above", "none of the \
above" or "both A and B".
- Does not give the answer away in its wording, and the correct option is not noticeably \
longer or more detailed than the others.
- Can be answered without a picture, a diagram, equipment or a passage to read.
- Uses everyday Kenyan settings where a setting helps, and never calls a learner he or she.

For each question also give:
- "options": each with its "text" and a "misconception". The correct option's \
misconception is an empty string. Each wrong option's misconception is one sentence for \
the teacher on what choosing it suggests the learner believes; do not repeat the option's \
text in it.
- "correct_option": the position of the correct answer in "options", counting from 0.
- "rationale": one sentence for the teacher on why the correct answer is right.
- "excerpt": a phrase of at most 25 words copied word for word from the curriculum text \
above, showing what the question assesses. Copy it exactly; do not reword it.

Write the rationale and misconceptions in the same language as the question. Spread the \
questions from easy to hard.
{existing_block}"""


# --- checks ----------------------------------------------------------------
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text: str) -> str:
    """Case, punctuation, bullets and spacing removed - what is compared."""
    return " ".join(_NON_WORD.sub(" ", text.casefold()).split())


def misconceptions_from(raw: Sequence[str], correct_option: int) -> list[str | None]:
    """The model's empty string at the key becomes None, as stored."""
    return [
        None if i == correct_option or not (m or "").strip() else m.strip()
        for i, m in enumerate(raw)
    ]


def option_parts(q: dict) -> tuple[list[str], list[str]]:
    """The option texts and their misconceptions, in option order."""
    options = [o for o in q.get("options", []) if isinstance(o, dict)]
    return (
        [(o.get("text") or "").strip() for o in options],
        [(o.get("misconception") or "").strip() for o in options],
    )


def question_problems(q: dict, chunk_texts: Sequence[str]) -> list[str]:
    """Why a generated question must be dropped, or [] if it may be saved."""
    options, raw_misconceptions = option_parts(q)
    key = q.get("correct_option")
    problems: list[str] = []

    if len(options) != OPTIONS:
        problems.append(f"has {len(options)} options, not {OPTIONS}")
    key_ok = isinstance(key, int) and 0 <= key < len(options)
    if key_ok and raw_misconceptions[key]:
        # Not repaired by blanking it: a misconception written against the
        # "correct" option suggests the model has the key in the wrong place.
        problems.append("the correct option cannot carry a misconception")
        misconceptions = None
    else:
        misconceptions = misconceptions_from(raw_misconceptions, key if key_ok else -1)
    problems += mcq_problems(options, key, misconceptions)
    if misconceptions is not None and isinstance(key, int) and 0 <= key < len(options):
        if any(m is None for i, m in enumerate(misconceptions) if i != key):
            problems.append("a wrong option has no misconception")

    question = (q.get("question") or "").strip()
    if len(question) < 5:
        problems.append("the question is empty")
    if not (q.get("rationale") or "").strip():
        problems.append("there is no rationale")

    if isinstance(key, int) and 0 <= key < len(options):
        answer = normalise(options[key])
        if len(answer) >= 4 and f" {answer} " in f" {normalise(question)} ":
            problems.append("the question contains its own answer")

    excerpt = normalise(q.get("excerpt") or "")
    if not excerpt:
        problems.append("there is no curriculum excerpt")
    elif len(excerpt.split()) > MAX_EXCERPT_WORDS:
        problems.append("the curriculum excerpt is too long to be a quotation")
    elif not any(excerpt in normalise(text) for text in chunk_texts):
        problems.append("the curriculum excerpt is not in the curriculum text")

    return problems


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
