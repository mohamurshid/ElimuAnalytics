"""
Phase 5 prompt tests.

The prompt is the mechanism. A sentence removed here changes what reaches a
teacher, and the grounding check is the only thing between a careless edit and
a fabricated KICD citation reaching a parent - so the sentences the 14 October
spike run proved necessary are pinned individually.

No API and no database: build_prompt is a pure function of its arguments.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from app.reports import (
    MAX_WORDS,
    RUBRIC_LEVELS,
    STRICT_CITATION,
    LearnerFacts,
    build_prompt,
    failure_block,
)

CHUNK = (
    "STRAND: 3.0 Force and Energy. SUB-STRAND: 3.3 Heat transfer. "
    "SUGGESTED LEARNING EXPERIENCES: carry out experiments to identify good and "
    "poor conductors of heat. "
    "Project 1: Learners to make oven gloves using locally available materials"
)

CHEBET = LearnerFacts(
    name="Chebet K.",
    grade="Grade 5",
    strand="3.0 Force and Energy",
    sub_strand="3.3 Heat Transfer",
    theta=-1.8,
    tier="Below expectation",
    items_answered=12,
    consecutive_flags=2,
)

PATTERN = {
    "answered": 12,
    "correct": 8,
    "unreported_failures": 0,
    "failed_items": [
        {
            "question": "Which of these is the best conductor of heat?",
            "chose": "A cotton cloth",
            "correct": "A metal spoon",
        },
        {
            "question": "Heat from the sun reaches the earth mainly by",
            "chose": "conduction",
            "correct": "radiation",
        },
    ],
}


# --------------------------------------------------------------------------
# The sentences the spike proved necessary
# --------------------------------------------------------------------------
def test_strict_citation_is_the_default():
    """The loose wording scored WEAK; the strict wording scored GROUNDED.

    Both were run on the same context in the same session. If strict ever
    stops being the default, reports stop being citable and the grounding
    check starts refusing export on everything.
    """
    assert STRICT_CITATION in build_prompt(CHEBET, [CHUNK])


def test_the_loose_wording_is_still_reachable_for_measurement():
    # Kept only so the Day 5 instrument can measure the difference against the
    # code that ships rather than its own copy of the prompt.
    assert STRICT_CITATION not in build_prompt(CHEBET, [CHUNK], strict=False)


def test_the_refusal_instruction_is_present():
    """This produced the wrong-context control's refusal - the single most
    important safety property in the system."""
    prompt = build_prompt(CHEBET, [CHUNK])
    assert "If the curriculum context does not cover this" in prompt
    assert "say so explicitly instead of writing a recommendation" in prompt


def test_the_no_invention_instruction_is_present():
    assert "Do not invent curriculum content" in build_prompt(CHEBET, [CHUNK])


def test_the_curriculum_context_is_the_retrieved_text_verbatim():
    # If the context is altered on the way in, a verbatim quotation of it stops
    # matching the stored chunk and the grounding check calls it fabricated.
    assert CHUNK in build_prompt(CHEBET, [CHUNK])


def test_several_chunks_are_all_included():
    second = "STRAND: 2.0 Matter. SUB-STRAND: 2.1 Mixtures."
    prompt = build_prompt(CHEBET, [CHUNK, second])
    assert CHUNK in prompt and second in prompt


def test_the_grade_is_the_learner_s_not_a_hard_coded_five():
    grade_four = LearnerFacts(**{**CHEBET.__dict__, "grade": "Grade 4"})
    prompt = build_prompt(grade_four, [CHUNK])
    assert "official KICD Grade 4 curriculum design" in prompt
    assert "Grade 5" not in prompt


def test_all_four_kicd_tiers_are_named():
    prompt = build_prompt(CHEBET, [CHUNK])
    for tier in RUBRIC_LEVELS:
        assert tier in prompt
    assert len(RUBRIC_LEVELS) == 4


def test_the_evidence_thresholds_come_from_the_irt_module():
    # Restating them here would let the prompt drift from the rule the engine
    # actually enforces.
    prompt = build_prompt(CHEBET, [CHUNK])
    assert "at least 5" in prompt
    assert "10 for confidence" in prompt


def test_the_word_limit_is_stated():
    assert f"Maximum {MAX_WORDS} words" in build_prompt(CHEBET, [CHUNK])


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------
def test_english_is_the_default():
    assert "Use clear, professional English." in build_prompt(CHEBET, [CHUNK])


def test_kiswahili_carries_the_respect_and_terminology_instructions():
    """Both were honoured unprompted in the 14 Oct Kiswahili arm.

    Haiku added "Hili ni ishara ya kumsaidia mapema, si hukumu kuhusu uwezo
    wake wa baadaye" and kept English technical terms in brackets. Neither
    behaviour is free; both are asked for here.
    """
    prompt = build_prompt(CHEBET, [CHUNK], language="Kiswahili")
    assert "Kiswahili sanifu" in prompt
    assert "never use words that imply the child is stupid" in prompt
    assert "English term in brackets" in prompt
    assert "Use clear, professional English." not in prompt


# --------------------------------------------------------------------------
# The item-level failure pattern
# --------------------------------------------------------------------------
def test_the_pattern_lists_each_wrong_answer_with_what_was_chosen():
    prompt = build_prompt(CHEBET, [CHUNK], failure_pattern=PATTERN)
    assert "ITEM-LEVEL FAILURE PATTERN (8 of 12 answered correctly)" in prompt
    assert "Which of these is the best conductor of heat?" in prompt
    assert "chose:   A cotton cloth" in prompt
    assert "correct: A metal spoon" in prompt


def test_the_pattern_uses_no_gendered_pronoun():
    """The spike's fixture was one named girl and its wording said "she chose".

    A report that misgenders a child is a failure no grounding check would
    catch, so nothing in this block refers to the learner by gender. Ungendered
    pronouns are fine and are used - "if THEY share one misconception" refers
    to the wrong answers, not to the child - so the assertion is about gendered
    words specifically, matched as whole words.
    """
    import re

    block = failure_block(PATTERN)
    gendered = re.findall(r"\b(she|he|her|hers|him|his)\b", block, re.I)
    assert gendered == []


def test_the_model_is_allowed_to_find_no_pattern():
    """The correction that matters most in this file.

    The spike said "name the misconception they share", which presumes one
    exists. The demonstration classroom draws distractors at random precisely
    so that no pattern is planted, so that instruction would have been an
    invitation to invent one.
    """
    block = failure_block(PATTERN)
    assert "If they do not share one, say so plainly" in block
    assert "Do not describe a pattern that is not there." in block


def test_wrong_answers_that_cannot_be_described_are_declared():
    pattern = {**PATTERN, "unreported_failures": 3}
    block = failure_block(pattern)
    assert "3 further wrong answer(s) were recorded without the option chosen" in block


def test_no_pattern_section_at_all_when_there_is_nothing_to_report():
    """A hand-marked assessment has no chosen options.

    An empty heading would leave the model interpreting a blank section; the
    section is simply absent.
    """
    assert failure_block(None) == ""
    assert failure_block({"answered": 3, "correct": 1, "failed_items": []}) == ""
    assert "ITEM-LEVEL" not in build_prompt(CHEBET, [CHUNK])


def test_the_learner_s_own_figures_appear():
    prompt = build_prompt(CHEBET, [CHUNK])
    assert "Chebet K." in prompt
    assert "-1.8" in prompt
    assert "Below expectation" in prompt
    assert "2 consecutive assessments" in prompt


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------
def test_a_missing_learner_field_fails_at_the_call_site():
    # A dict would have produced a KeyError inside an f-string, mid-prompt.
    with pytest.raises(TypeError):
        LearnerFacts(name="X", grade="Grade 5")  # type: ignore[call-arg]


def test_learner_facts_cannot_be_mutated_after_construction():
    # frozen=True, so nothing can slip an extra claim into the prompt by
    # mutating the facts object after it was built.
    with pytest.raises(FrozenInstanceError):
        CHEBET.theta = 0.0  # type: ignore[misc]


def test_the_three_paragraph_structure_is_requested():
    prompt = build_prompt(CHEBET, [CHUNK])
    for paragraph in ("Paragraph 1:", "Paragraph 2:", "Paragraph 3:"):
        assert paragraph in prompt
