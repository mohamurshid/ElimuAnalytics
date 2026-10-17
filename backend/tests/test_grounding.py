"""
Phase 5 grounding tests.

The fixtures are real. V4_CHUNK is the Grade 5 Heat Transfer text the v4
extractor produces from GRADE.5.SCIENCE.pdf, and REPORT_STRICT is the report
claude-haiku-5-5 actually wrote in the 14 October spike run under the strict
verbatim-citation prompt. So these tests check the shipped checker against the
shipped corpus and a real model output, not against something invented to pass.

The pair test_the_real_report_verifies_against_the_v4_chunk /
test_the_same_report_is_FABRICATED_against_the_v3_chunk is the one worth
keeping forever. It encodes, as a regression, the reason the extractor had to
be fixed: the report quotes a KICD Project, v3 dropped every Project at the
page break, and so the exact report that earned a GROUNDED verdict in the
spike would have been marked FABRICATED by the production checker against the
production corpus. The spike was right and the corpus was wrong.
"""

from __future__ import annotations

import pytest
from app.grounding import (
    MIN_QUOTE_WORDS,
    VAGUE_PHRASES_SW,
    check,
    lexical_overlap,
    verbatim_quotes,
)

# Excerpt of the v4 chunk - the Suggested Learning Experiences through the two
# Projects. The bullet is U+F0B7 as it arrives from the PDF, before
# curriculum.normalise() repairs it, which is also a small check that the
# checker does not depend on the repair having happened.
V4_CHUNK = (
    "SUGGESTED LEARNING EXPERIENCES: The learner is guided to: "
    "● brainstorm on the meanings of the terms conduction, convection and radiation "
    "as used in heat transfer, ● carry out experiments to identify good and poor "
    "conductors of heat, KEY INQUIRY QUESTION: 1. How is heat transferred through "
    "materials in nature?  discuss Safety precautions when handling heat "
    "● discuss various ways of responding to fire emergencies. "
    "Project 1: Learners to make oven gloves using locally available materials "
    "Project 2: Learners to make a fireless cooker"
)

# The same sub-strand as v3 extracted it: the row stops at the page break, so
# both Projects are absent.
V3_CHUNK = V4_CHUNK[: V4_CHUNK.index(" discuss Safety")]

# Paragraph 3 of the real strict-prompt report, 14 Oct 2026.
REPORT_STRICT = (
    'I recommend the named project: "Learners to make oven gloves using locally '
    'available materials." This addresses outcome (b) because Chebet can test local '
    "materials to identify which are poor conductors. Run it in small guided groups."
)


# --------------------------------------------------------------------------
# The regression that justifies the v4 extractor
# --------------------------------------------------------------------------
def test_the_real_report_verifies_against_the_v4_chunk():
    result = check(REPORT_STRICT, V4_CHUNK)
    assert result["verdict"] == "GROUNDED"
    assert result["exportable"] is True
    assert result["verbatim_quotes_verified"] == [
        "Learners to make oven gloves using locally available materials."
    ]
    assert result["verbatim_quotes_fabricated"] == []


def test_the_same_report_is_FABRICATED_against_the_v3_chunk():
    """Why the page-break fix was not optional.

    Nothing about the model or the prompt changes between this test and the one
    above - only which version of the extractor produced the curriculum text.
    Against v3 the quotation cannot be found, so the checker correctly reports
    a fabricated citation and refuses export, and the spike's headline result
    is unreproducible in production.
    """
    result = check(REPORT_STRICT, V3_CHUNK)
    assert result["verdict"] == "FABRICATED"
    assert result["exportable"] is False
    assert result["verbatim_quotes_verified"] == []


# --------------------------------------------------------------------------
# Quote verification
# --------------------------------------------------------------------------
def test_a_quote_lifted_from_the_curriculum_is_verified():
    report = 'Use this: "carry out experiments to identify good and poor conductors of heat".'
    verified, fabricated = verbatim_quotes(report, V4_CHUNK)
    assert len(verified) == 1 and not fabricated


def test_an_invented_quote_is_caught():
    report = 'The curriculum says "learners should build a solar water heater from scrap".'
    verified, fabricated = verbatim_quotes(report, V4_CHUNK)
    assert not verified and len(fabricated) == 1


def test_whitespace_differences_do_not_break_verification():
    # The model rewraps lines; the curriculum carries runs of spaces from the
    # PDF. Neither should make a true citation look false.
    report = 'Quote: "Learners   to make\n oven gloves using locally available materials"'
    verified, _ = verbatim_quotes(report, V4_CHUNK)
    assert len(verified) == 1


def test_curly_quotation_marks_are_read_too():
    report = "“Learners to make a fireless cooker” is the project."
    verified, fabricated = verbatim_quotes(report, V4_CHUNK)
    assert len(verified) == 1 and not fabricated


def test_a_quoted_fragment_too_short_to_be_a_citation_is_ignored():
    """Quoting one word is not citing the curriculum.

    Without this, a report saying the learner struggles with "conduction"
    would earn a verified citation and a GROUNDED verdict on the strength of a
    single word that appears in the context by coincidence.
    """
    report = 'She confuses "conduction" with "radiation".'
    verified, fabricated = verbatim_quotes(report, V4_CHUNK)
    assert not verified and not fabricated
    assert check(report, V4_CHUNK)["verdict"] == "WEAK"


def test_the_minimum_quote_length_is_what_it_says():
    words = " ".join(["locally"] * MIN_QUOTE_WORDS)
    assert len(words.split()) == MIN_QUOTE_WORDS


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------
def test_a_report_that_cites_nothing_is_WEAK_not_GROUNDED():
    report = (
        "Chebet is below expectation on Heat Transfer. She should work on "
        "conduction, convection and radiation through practical activities."
    )
    result = check(report, V4_CHUNK)
    assert result["verdict"] == "WEAK"
    assert result["exportable"] is False


def test_one_fabricated_quote_outweighs_a_verified_one():
    """A report that cites correctly once and invents once is not grounded.

    The fabricated span is the dangerous half: it looks like evidence, and a
    teacher cannot tell. A verdict that averaged the two would let it through.
    """
    report = (
        '"Learners to make a fireless cooker" and also '
        '"learners should construct a parabolic solar oven from foil".'
    )
    result = check(report, V4_CHUNK)
    assert result["verdict"] == "FABRICATED"
    assert result["exportable"] is False
    assert len(result["verbatim_quotes_verified"]) == 1
    assert len(result["verbatim_quotes_fabricated"]) == 1


def test_exportable_tracks_the_verdict_and_nothing_else():
    assert check(REPORT_STRICT, V4_CHUNK)["exportable"] is True
    assert check("No citation here at all, just advice.", V4_CHUNK)["exportable"] is False


# --------------------------------------------------------------------------
# Vague phrases are recorded and never decisive
# --------------------------------------------------------------------------
def test_vague_phrases_are_reported_but_do_not_block_export():
    """The deliberate decision recorded in grounding.py and models.Report.

    The list is a heuristic and its Kiswahili half is unvalidated, so letting
    it block export would mean a wrong entry stops a good report reaching a
    parent. It is reported so a teacher and an examiner can see it.
    """
    report = REPORT_STRICT + " She also needs extra practice and more attention."
    result = check(report, V4_CHUNK)
    assert "extra practice" in result["vague_phrases_en"]
    assert "more attention" in result["vague_phrases_en"]
    assert result["verdict"] == "GROUNDED"
    assert result["exportable"] is True


def test_the_kiswahili_phrase_the_english_list_missed_is_now_seen():
    # From the 14 Oct Kiswahili arm: Sonnet wrote "hitaji la mazoezi zaidi ya
    # vitendo" - a need for more practical exercises - which the English list
    # would have flagged and the Kiswahili list did not yet exist to catch.
    result = check("Anahitaji mazoezi zaidi ya vitendo.", V4_CHUNK)
    assert "mazoezi zaidi" in result["vague_phrases_sw"]
    assert result["vague_phrases_en"] == []


@pytest.mark.parametrize("phrase", VAGUE_PHRASES_SW)
def test_every_kiswahili_phrase_is_detectable(phrase):
    # Guards against a typo or stray whitespace making an entry dead.
    assert phrase in check(f"Mwalimu: {phrase} itasaidia.", V4_CHUNK)["vague_phrases_sw"]


# --------------------------------------------------------------------------
# Lexical overlap is diagnostic only
# --------------------------------------------------------------------------
def test_overlap_is_recorded_but_cannot_earn_a_verdict():
    """The v2 lesson, kept as a test.

    A report can echo the curriculum's vocabulary heavily without citing it.
    The spike's no-context ablation produced fluent domain language with no
    curriculum supplied at all, so overlap cannot distinguish grounding from
    fluency and must not decide.
    """
    echo = (
        "conduction convection radiation conductors experiments transfer "
        "materials precautions insulation"
    )
    result = check(echo, V4_CHUNK)
    assert result["lexical_overlap"] > 0.5
    assert result["verdict"] == "WEAK"
    assert result["exportable"] is False


def test_overlap_of_nothing_is_zero_not_an_error():
    assert lexical_overlap("", V4_CHUNK) == 0.0
    assert check("", V4_CHUNK)["verdict"] == "WEAK"
