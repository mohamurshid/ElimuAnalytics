"""
Building the prompt for a grounded diagnostic report, and calling the model.

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

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .irt import CONFIDENT_RESPONSES, MIN_RESPONSES, TIER_CUTS

RUBRIC_LEVELS = [name for _cut, name in TIER_CUTS]
# Raised from the spike's 200 after the first live report came in at 265
# English words. The spike measured a report with no failure pattern; one that
# describes up to twelve wrong answers, by what each question asked rather than
# by a number, cannot do it in 200. A limit that is always breached teaches the
# model to ignore limits.
MAX_WORDS = 250

# claude-sonnet-5-5 was dropped after the 14 October run: 9.5x the cost of
# haiku-5-5 ($0.009944 against $0.001139 for the same Kiswahili report) for an
# equivalent grounding result - both GROUNDED with one verified citation.
MODEL = "claude-haiku-5-5"
EFFORT = "low"
MAX_TOKENS = 4000

# USD per million tokens (input, output), checked against the published price
# list on 14 October 2026. Haiku 5.5 is priced in two bands - these are the
# low band, below 100K input tokens, which is the only band a report prompt of
# roughly 750 tokens can reach.
PRICING = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

# A callable with the shape of anthropic's `client.messages.create`.
Generator = Callable[..., Any]

_generator: Generator | None = None

KISWAHILI_INSTRUCTION = (
    "Andika ripoti yote kwa Kiswahili sanifu kinachotumika shuleni Kenya. "
    "Write the entire report in the standard Kiswahili used in Kenyan schools. "
    "Use respectful language about the learner at all times; never use words that "
    "imply the child is stupid or ignorant. Where an accurate Kiswahili technical "
    "term does not exist, give the Kiswahili term followed by the English term in "
    "brackets rather than inventing a word."
)
ENGLISH_INSTRUCTION = "Use clear, professional English."

# The first live report said "She answered 12 items" and "she may treat metals
# as poor conductors", inferring gender from the name "Chebet K." Nothing in
# the database records a learner's gender, so that is a guess - and no
# grounding check can catch a misgendered child in a document that goes home to
# a parent. Kenyan names are not uniformly gendered, and the cost of being
# wrong is a credibility failure that has nothing to do with the system's
# actual accuracy.
NO_GENDER = (
    "Refer to the learner by name, or as \"the learner\". Do NOT use he, she, "
    "him, her, his or hers: the learner's gender is not recorded and must not "
    "be inferred from their name."
)

# The second half of this was added on 18 October, after a spike run scored a
# good report FABRICATED. The model had quoted the KICD project correctly AND
# put quotation marks around its own plain-words statement of the learner's
# misconception - "A material that is bad at carrying heat also lets heat out
# fast." The grounding check treats every quoted span of five or more words as
# a citation claim, so a quoted misconception is indistinguishable from an
# invented curriculum quotation, and the report was refused export.
#
# The check is not what changed. Its strictness is what makes a GROUNDED
# verdict mean anything, and softening it to guess which quotations are
# citations would be guessing on exactly the question it exists to answer.
# What was missing was any statement of what quotation marks are FOR. The
# prompt forbade quoting outside the context and never said what to do
# instead, and naming a misconception "in plain words a teacher can use" is
# an invitation to quote it.
STRICT_CITATION = (
    "In Paragraph 3 you MUST quote the chosen activity verbatim from the SUGGESTED "
    "LEARNING EXPERIENCES or PROJECTS above, inside double quotation marks, exactly "
    "as written, before explaining how the teacher should run it. Prefer a named "
    "PROJECT where one exists. Do not paraphrase the quoted part, and do not quote "
    "anything that is not in the context above.\n"
    "Quotation marks are reserved for that citation and for nothing else. Do NOT "
    "put quotation marks around a misconception you are naming, around the "
    "learner's own reasoning, around a question you are referring to, or around a "
    "phrase you want to emphasise - write all of those in plain prose. Any quoted "
    "span that is not in the curriculum context above is recorded as a fabricated "
    "citation and the whole report is refused, however good the rest of it is."
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
    # The grade of the curriculum design the strand comes from, when it is
    # not the learner's own - a Grade 5 learner assessed on a Grade 4
    # sub-strand. None means the same grade, and leaves the prompt exactly as
    # it was before this field existed, so earlier measurements still hold.
    curriculum_grade: str | None = None


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
    for item in failed:
        lines.append(f"  - {item['question']}")
        lines.append(f"      chose:   {item['chose']}")
        lines.append(f"      correct: {item['correct']}")

    if pattern.get("unreported_failures"):
        lines.append(
            f"  Note: {pattern['unreported_failures']} further wrong answer(s) were "
            f"recorded without the option chosen, and cannot be described here."
        )

    lines.append(
        "  Refer to any of these by what the question asked - for example \"the "
        "question about the metal spoon in hot porridge\" - and NEVER by a number "
        "or a position in this list. These items are not numbered anywhere the "
        "teacher can see them, so \"items 4 to 6\" is unusable in a report."
    )
    lines.append(
        "  Read these together. If they share one misconception, name it in plain "
        "words a teacher can use, WITHOUT quotation marks around it. If they do not "
        "share one, say so plainly and name which Specific Learning Outcomes the "
        "wrong answers fall under instead. Do not describe a pattern that is not "
        "there."
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

    design_grade = learner.curriculum_grade or learner.grade

    return f"""{opening}

CURRICULUM CONTEXT (retrieved from the official KICD {design_grade} curriculum design):
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
{NO_GENDER}

{language_line} Maximum {MAX_WORDS} words. Do not invent curriculum content that is
not present in the context above. If the curriculum context does not cover this
learner's sub-strand, say so explicitly instead of writing a recommendation."""


# ---------------------------------------------------------------------------
# Calling the model
# ---------------------------------------------------------------------------
def set_generator(generator: Generator | None) -> None:
    """Install a generator, or pass None to fall back to the real client."""
    global _generator
    _generator = generator


def get_generator() -> Generator:
    global _generator
    if _generator is None:
        _generator = _load_anthropic()
    return _generator


def _load_anthropic() -> Generator:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set, so no report can be generated. "
            'Windows: setx ANTHROPIC_API_KEY "sk-ant-..." then reopen the terminal.'
        )
    # Imported here, not at module scope, so that importing this module does
    # not require the anthropic package - the same laziness db.py applies to
    # the database driver.
    from anthropic import Anthropic

    return Anthropic().messages.create


def report_text(response: Any) -> str:
    """The report, and only the report.

    Thinking blocks are discarded rather than concatenated. They are the
    model's scratch work: never shown to a teacher, so not part of the
    artefact under test, and they quote the supplied curriculum freely while
    reasoning - so scoring them would inflate every grounding result.
    """
    return "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()


def thinking_tokens(usage: Any) -> int | None:
    """How many of the billed output tokens were internal reasoning."""
    details = getattr(usage, "output_tokens_details", None)
    return getattr(details, "thinking_tokens", None) if details else None


def price(model: str, usage: Any) -> float | None:
    # Longest prefix wins: "claude-sonnet-5" is a prefix of
    # "claude-sonnet-5-5", so first-match-in-dict-order would silently price
    # the wrong model as soon as another row is added.
    key = max((k for k in PRICING if model.startswith(k)), key=len, default=None)
    if key is None:
        return None
    per_in, per_out = PRICING[key]
    return usage.input_tokens / 1e6 * per_in + usage.output_tokens / 1e6 * per_out


@dataclass(frozen=True)
class Generated:
    """One model response, with everything needed to audit it later."""

    text: str
    model: str
    effort: str
    stop_reason: str | None
    truncated: bool
    empty: bool
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None
    cost_usd: float | None


def generate(
    prompt: str,
    *,
    model: str = MODEL,
    effort: str = EFFORT,
    max_tokens: int = MAX_TOKENS,
) -> Generated:
    """Send the prompt and return the report with its accounting."""
    response = get_generator()(
        model=model,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
    )
    text = report_text(response)
    return Generated(
        text=text,
        model=model,
        effort=effort,
        stop_reason=getattr(response, "stop_reason", None),
        truncated=getattr(response, "stop_reason", None) == "max_tokens",
        empty=not text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        thinking_tokens=thinking_tokens(response.usage),
        cost_usd=price(model, response.usage),
    )
