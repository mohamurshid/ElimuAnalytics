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
from types import SimpleNamespace

import pytest
from app.reports import (
    EFFORT,
    MAX_TOKENS,
    MAX_WORDS,
    MODEL,
    NO_GENDER,
    PRICING,
    RUBRIC_LEVELS,
    STRICT_CITATION,
    Generated,
    LearnerFacts,
    build_prompt,
    failure_block,
    generate,
    price,
    report_text,
    set_generator,
    thinking_tokens,
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


def test_the_word_limit_allows_for_a_failure_pattern():
    # The spike's 200 was measured on a report with no failure pattern. The
    # first live report, describing twelve wrong answers, came in at 265.
    assert MAX_WORDS >= 250


def test_the_learner_is_never_gendered():
    """The first live report said "She answered 12 items".

    Gender is not recorded anywhere and was inferred from the name. No
    grounding check can catch a misgendered child in a document that goes home
    to a parent.
    """
    prompt = build_prompt(CHEBET, [CHUNK])
    assert NO_GENDER in prompt
    assert "Do NOT use he, she" in prompt
    assert 'as "the learner"' in prompt


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


def test_the_wrong_answers_are_not_numbered():
    """The defect the first live report exposed.

    The block used to number the list 1., 2., 3. and the model duly wrote
    "Items 4, 5, 6 and 8" - indices that exist only inside the prompt. A
    teacher holding that report has no way to discover which questions those
    were, so the most actionable paragraph was unactionable.
    """
    block = failure_block(PATTERN)
    assert "1." not in block
    assert "2." not in block
    assert block.count("  - ") == len(PATTERN["failed_items"])


def test_the_model_is_told_to_name_the_question_not_a_number():
    block = failure_block(PATTERN)
    assert "NEVER by a number" in block
    assert "not numbered anywhere the teacher can see" in block


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


# --------------------------------------------------------------------------
# Calling the model. The generator is always a stub; see reports.py.
# --------------------------------------------------------------------------
def block(kind: str, **fields):
    return SimpleNamespace(type=kind, **fields)


def fake_response(
    *,
    text: str = "A grounded report.",
    thinking: str | None = "scratch work quoting oven gloves verbatim",
    stop_reason: str = "end_turn",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    thinking_token_count: int | None = 300,
):
    content = []
    if thinking is not None:
        content.append(block("thinking", thinking=thinking))
    if text:
        content.append(block("text", text=text))
    details = (
        SimpleNamespace(thinking_tokens=thinking_token_count)
        if thinking_token_count is not None
        else None
    )
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_tokens_details=details,
        ),
    )


@pytest.fixture(autouse=True)
def _no_live_api():
    """Nothing in this module may reach the network, even by accident."""
    set_generator(lambda **kwargs: fake_response())
    yield
    set_generator(None)


def test_the_report_is_the_text_block_not_the_first_block():
    """What crashed the first run of the refreshed spike.

    Adaptive thinking cannot be disabled on these models, so content[0] is
    often a ThinkingBlock, which has no `.text` at all.
    """
    assert report_text(fake_response(text="THE REPORT")) == "THE REPORT"


def test_thinking_is_discarded_rather_than_concatenated():
    """Scratch work quotes the context freely while reasoning.

    Concatenating it would hand the grounding check a document full of
    verified citations the report itself never made - the same class of
    measurement error the v2 spike made with generic vocabulary.
    """
    text = report_text(fake_response(text="THE REPORT"))
    assert "oven gloves" not in text


def test_several_text_blocks_are_joined():
    response = fake_response()
    response.content = [block("text", text="A"), block("text", text="B")]
    assert report_text(response) == "A\nB"


def test_a_response_of_pure_thinking_yields_nothing():
    assert report_text(fake_response(text="", thinking="only thinking")) == ""


def test_the_wire_call_carries_the_settings_the_spike_settled_on():
    seen: dict = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return fake_response()

    set_generator(spy)
    generate("PROMPT")

    assert seen["model"] == MODEL == "claude-haiku-5-5"
    assert seen["max_tokens"] == MAX_TOKENS == 4000
    assert seen["output_config"] == {"effort": EFFORT} == {"effort": "low"}
    assert seen["messages"] == [{"role": "user", "content": "PROMPT"}]


def test_generation_records_everything_needed_to_audit_it():
    result = generate("PROMPT")
    assert isinstance(result, Generated)
    assert result.text == "A grounded report."
    assert (result.model, result.effort) == (MODEL, EFFORT)
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.thinking_tokens == 300
    assert result.truncated is False
    assert result.empty is False


def test_truncation_is_flagged_rather_than_raised():
    """The policy is save, flag, refuse export - so the caller needs a flag.

    Raising would lose the evidence that a truncated generation happened at
    all, which is the thing worth knowing.
    """
    set_generator(lambda **kw: fake_response(stop_reason="max_tokens"))
    result = generate("PROMPT")
    assert result.truncated is True
    assert result.stop_reason == "max_tokens"


def test_an_empty_report_is_flagged_not_raised():
    set_generator(lambda **kw: fake_response(text="", thinking="all thinking"))
    result = generate("PROMPT")
    assert result.empty is True
    assert result.text == ""


def test_thinking_tokens_are_optional_and_never_crash():
    assert thinking_tokens(SimpleNamespace()) is None
    assert thinking_tokens(SimpleNamespace(output_tokens_details=None)) is None
    assert (
        thinking_tokens(SimpleNamespace(output_tokens_details=SimpleNamespace(thinking_tokens=7)))
        == 7
    )


def test_cost_is_computed_from_the_published_rates():
    result = generate("PROMPT")
    # 1000 in at $0.10/MTok + 500 out at $0.50/MTok
    assert result.cost_usd == pytest.approx(1000 / 1e6 * 0.10 + 500 / 1e6 * 0.50)


def test_pricing_takes_the_longest_matching_prefix():
    """"claude-sonnet-5" is a prefix of "claude-sonnet-5-5".

    First-match-in-dict-order priced the wrong model in the spike, silently.
    """
    usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0)
    assert price("claude-sonnet-5-5", usage) == pytest.approx(2.00)

    PRICING["claude-sonnet-5"] = (99.0, 99.0)
    try:
        assert price("claude-sonnet-5-5", usage) == pytest.approx(2.00)
    finally:
        del PRICING["claude-sonnet-5"]


def test_an_unpriced_model_reports_no_cost_rather_than_zero():
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500)
    assert price("some-other-model", usage) is None


def test_clearing_the_generator_does_not_load_the_client():
    # The fallback is lazy; set_generator(None) must not import anthropic or
    # require a key.
    set_generator(None)
    from app import reports

    assert reports._generator is None
