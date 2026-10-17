"""
Building the prompt for a grounded diagnostic report.

This is the prompt the Day 5 spike measured, moved out of the spike and
parameterised. Six conditions in the 14 October run decided its shape, and the
reasoning for each part is recorded here because the wording IS the mechanism -
a change to a sentence in this file changes what reaches a teacher, and the
only thing standing between a careless edit and a fabricated citation is the
grounding check.

WHAT THE MEASUREMENTS DECIDED
-----------------------------
STRICT CITATION IS NOT OPTIONAL. The loose wording and the strict wording were
run side by side on the same context. The loose one named curriculum
vocabulary and cited nothing; once the inflated anchor counts were corrected it
scored WEAK, not GROUNDED. The strict one quoted a KICD project verbatim and
scored GROUNDED. `strict` therefore defaults to True; the flag survives only so
the Day 5 instrument can keep measuring the difference against the code that
ships rather than against its own private copy.

THE REFUSAL INSTRUCTION EARNS ITS PLACE. Handed plants curriculum for a
heat-transfer learner, the model named the mismatch and declined to recommend
anything, leaking no plant content. That is the single most important safety
property in the system and it comes from the last sentence of the prompt.

THE ITEM-LEVEL FAILURE PATTERN IS WHAT MAKES A REPORT USEFUL. Without it both
English conditions said, unprompted, that the breakdown was missing and the
failing outcome could not be confirmed. With it the report named the
misconception - "she believes heat only moves through direct touch" - and tied
the recommended activity back to the exact question the learner got wrong. It
cost 8% more in tokens.

TWO CORRECTIONS TO THE SPIKE'S WORDING
--------------------------------------
The spike said "the N she got wrong" and "she chose", because its fixture was
one named girl. A report that misgenders a child is a failure no grounding
check would catch, so nothing here carries a pronoun.

More seriously, the spike instructed the model to "name the misconception they
share". That presumes a shared misconception exists. Against the demonstration
classroom - where distractors are drawn at random precisely so that no pattern
is planted - that instruction is an invitation to invent one. It now permits,
and names, the possibility that there is no single misconception.
"""

from __future__ import annotations

from dataclasses import dataclass

from .irt import CONFIDENT_RESPONSES, MIN_RESPONSES, TIER_CUTS

RUBRIC_LEVELS = [name for _cut, name in TIER_CUTS]
MAX_WORDS = 200

KISWAHILI_INSTRUCTION = (
    "Andika ripoti yote kwa Kiswahili sanifu kinachotumika shuleni Kenya. "
    "Write the entire report in the standard Kiswahili used in Kenyan schools. "
    "Use respectful language about the learner at all times; never use words that "
    "imply the child is stupid or ignorant. Where an accurate Kiswahili technical "
    "term does not exist, give the Kiswahili term followed by the English term in "
    "brackets rather than inventing a word."
)
ENGLISH_INSTRUCTION = "Use clear, professional English."

STRICT_CITATION = (
    "In Paragraph 3 you MUST quote the chosen activity verbatim from the SUGGESTED "
    "LEARNING EXPERIENCES or PROJECTS above, inside double quotation marks, exactly "
    "as written, before explaining how the teacher should run it. Prefer a named "
    "PROJECT where one exists. Do not paraphrase the quoted part, and do not quote "
    "anything that is not in the context above."
)


@dataclass(frozen=True)
class LearnerFacts:
    """What the report is allowed to assert about a learner.

    A frozen dataclass rather than a dict so that a missing field is a
    TypeError at the call site instead of a KeyError inside an f-string, and so
    that nothing can be added to the prompt by mutating what was passed in.
    """

    name: str
    grade: str
    strand: str
    sub_strand: str
    theta: float
    tier: str
    items_answered: int
    consecutive_flags: int


def failure_block(pattern: dict | None) -> str:
    """The learner's wrong answers and the option chosen for each.

    Returns "" when there is nothing describable, so a report built from
    hand-marked assessments simply has no such section rather than an empty
    heading the model has to interpret.
    """
    if not pattern or not pattern.get("failed_items"):
        return ""

    failed = pattern["failed_items"]
    lines = [
        "",
        f"ITEM-LEVEL FAILURE PATTERN ({pattern['correct']} of {pattern['answered']} "
        f"answered correctly). The {len(failed)} wrong answers, each with the option "
        f"the learner chose:",
    ]
    for n, item in enumerate(failed, 1):
        lines.append(f"  {n}. {item['question']}")
        lines.append(f"     chose:   {item['chose']}")
        lines.append(f"     correct: {item['correct']}")

    if pattern.get("unreported_failures"):
        lines.append(
            f"  Note: {pattern['unreported_failures']} further wrong answer(s) were "
            f"recorded without the option chosen, and cannot be described here."
        )

    lines.append(
        "  Read these together. If they share one misconception, name it in plain "
        "words a teacher can use. If they do not share one, say so plainly and name "
        "which Specific Learning Outcomes the wrong answers fall under instead. Do "
        "not describe a pattern that is not there."
    )
    return "\n".join(lines)


def build_prompt(
    learner: LearnerFacts,
    chunk_texts: list[str],
    *,
    language: str = "English",
    strict: bool = True,
    failure_pattern: dict | None = None,
) -> str:
    """The full prompt. `chunk_texts` are curriculum chunks as stored."""
    context = "\n\n".join(chunk_texts)
    language_line = (
        ENGLISH_INSTRUCTION if language == "English" else KISWAHILI_INSTRUCTION
    )
    citation_line = f"\n{STRICT_CITATION}\n" if strict else ""
    evidence_line = (
        f"- Items answered in this sub-strand: {learner.items_answered} "
        f"(an estimate needs at least {MIN_RESPONSES}; "
        f"{CONFIDENT_RESPONSES} for confidence)"
    )

    opening = (
        "You are an educational advisor writing a diagnostic report for a Kenyan "
        "primary school teacher."
    )

    return f"""{opening}

CURRICULUM CONTEXT (retrieved from the official KICD {learner.grade} curriculum design):
{context}

LEARNER PERFORMANCE:
- Learner: {learner.name}, {learner.grade}
- Strand: {learner.strand}
- Sub-strand: {learner.sub_strand}
- Estimated ability (IRT theta): {learner.theta}
- KICD rubric level: {learner.tier}
{evidence_line}
- Flagged as at-risk for {learner.consecutive_flags} consecutive assessments
{failure_block(failure_pattern)}

The KICD rubric levels are: {", ".join(RUBRIC_LEVELS)}

Write a 3-paragraph report addressed to the class teacher:
Paragraph 1: Summarise the learner's current standing against the KICD rubric level.
Paragraph 2: Identify the specific gap, referencing the Specific Learning Outcomes
             from the curriculum context above.
Paragraph 3: Recommend ONE concrete classroom activity, drawn directly from the
             Suggested Learning Experiences in the curriculum context.
{citation_line}
{language_line} Maximum {MAX_WORDS} words. Do not invent curriculum content that is
not present in the context above. If the curriculum context does not cover this
learner's sub-strand, say so explicitly instead of writing a recommendation."""
