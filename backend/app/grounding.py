"""
Is a generated report actually grounded in the curriculum it was given?

Ported from the Day 5 spike, with one deliberate reduction.

WHAT THE SPIKE DID, AND WHY IT CANNOT SHIP AS IT WAS
----------------------------------------------------
The spike counted hand-written "distinctive anchors" per chunk - phrases such
as "oven gloves" and "fireless cooker" that appear in KICD's document and
essentially nowhere else. That worked because the spike covered eight chunks.
The corpus has 1,617, across six grades and fourteen learning areas, and
nobody is going to hand-write anchors for all of them. An instrument that only
works on the sub-strand it was built for is not an instrument.

So the anchors are gone, and what remains is the check that generalises on its
own: a quotation, verified character for character against the curriculum text
that was actually supplied to the model.

That is also the signal that did the work. In the 14 Oct run the loose prompt
and the strict prompt both named curriculum vocabulary, and what separated
them was a verified quotation - one had it, the other did not. Deduplicating
the anchors dropped the loose prompt from GROUNDED to WEAK while the strict
prompt, which quotes, stayed GROUNDED. The quotation is the evidence.

THE VERDICTS
------------
  FABRICATED  something appeared in quotation marks that is not in the
              supplied curriculum. The worst failure available, because it
              looks like evidence, and a teacher has no way to tell. Not
              exportable.
  GROUNDED    at least one quotation verified against the supplied curriculum,
              and nothing fabricated. Exportable.
  WEAK        no quotation at all, and nothing fabricated. The report may well
              be sensible, but nothing in it is traceable to the curriculum,
              which is the claim the system makes. Not exportable.

A note on what is NOT a verdict. The spike also had a LEAKED verdict for
content drawn from a chunk that was not supplied. Here that collapses into
FABRICATED, which is the correct handling: a quotation that is not in the
supplied context fails, whether the model invented it or lifted it from
somewhere else. The diagnostic distinction can be recovered later by searching
the corpus for the offending span; the pass/fail decision does not need it.

VAGUE PHRASES NEVER DECIDE
--------------------------
"Give her extra practice" is advice that required no curriculum, and the spike
tracked it to prove RAG was adding something. It is still tracked and still
reported. But it does not affect the verdict and does not block export,
because the list is a heuristic and its Kiswahili half has NOT yet been
checked by a Kiswahili speaker. A wrong entry there would block a perfectly
good report from reaching a parent, which is a worse failure than noting a
cliche. If the Kiswahili list is validated later, that decision can be
revisited on purpose rather than by accident.
"""

from __future__ import annotations

import re

MIN_QUOTE_WORDS = 5

# Advice that needed no curriculum to produce. English list carried over from
# the spike unchanged.
VAGUE_PHRASES_EN = [
    "extra practice",
    "more practice",
    "additional practice",
    "additional exercises",
    "more exercises",
    "practice questions",
    "one-on-one",
    "one on one",
    "remedial",
    "revise the topic",
    "extra time",
    "pay more attention",
    "work harder",
    "extra support",
    "more attention",
]

# UNVALIDATED. A starter list, written from the Kiswahili arm of the 14 Oct
# spike run, where Sonnet produced "hitaji la mazoezi zaidi ya vitendo" - "a
# need for more practical exercises" - which the English list would have caught
# and this one was not yet there to. It needs a Kiswahili speaker to confirm
# each entry is a cliche rather than ordinary pedagogical language. Until then
# these are reported and never decisive, which is why adding them is safe.
VAGUE_PHRASES_SW = [
    "mazoezi zaidi",
    "mazoezi ya ziada",
    "msaada wa ziada",
    "muda wa ziada",
    "ajitahidi zaidi",
    "umakini zaidi",
    "azingatie zaidi",
    "marudio",
]

_QUOTED = re.compile(r'"([^"]{10,400})"|“([^”]{10,400})”')
_WHITESPACE = re.compile(r"\s+")

STOPWORDS = {
    "learner",
    "learners",
    "should",
    "their",
    "there",
    "these",
    "those",
    "which",
    "about",
    "would",
    "could",
    "being",
    "through",
}


def _flatten(text: str) -> str:
    return _WHITESPACE.sub(" ", text.lower()).strip()


def verbatim_quotes(report: str, context: str) -> tuple[list[str], list[str]]:
    """Every quoted span in the report, split into verified and fabricated.

    Whitespace is flattened on both sides before comparing, because the model
    rewraps lines and the curriculum text carries runs of spaces from the PDF.
    Spans shorter than MIN_QUOTE_WORDS words are ignored: a model quoting the
    single word "conduction" is not citing anything, and treating it as a
    citation would let a one-word quotation carry a GROUNDED verdict.
    """
    flat_context = _flatten(context)
    verified: list[str] = []
    fabricated: list[str] = []

    for match in _QUOTED.finditer(report):
        span = match.group(1) or match.group(2) or ""
        normalised = _flatten(span.strip(" .;:,"))
        if len(normalised.split()) < MIN_QUOTE_WORDS:
            continue
        (verified if normalised in flat_context else fabricated).append(span.strip())

    return verified, fabricated


def lexical_overlap(report: str, context: str) -> float:
    """Share of the report's content words that also occur in the context.

    Diagnostic only. It never decides a verdict: the spike's no-context
    ablation showed a model producing plausible domain vocabulary with no
    curriculum at all, so overlap alone cannot distinguish grounding from
    fluency.
    """
    context_words = set(re.findall(r"[a-z]{5,}", _flatten(context)))
    report_words = [
        w for w in re.findall(r"[a-z]{5,}", _flatten(report)) if w not in STOPWORDS
    ]
    if not report_words:
        return 0.0
    return sum(1 for w in report_words if w in context_words) / len(report_words)


def check(report: str, context: str) -> dict:
    """Grade one report against the curriculum text it was given."""
    verified, fabricated = verbatim_quotes(report, context)
    low = _flatten(report)
    vague_en = [p for p in VAGUE_PHRASES_EN if p in low]
    vague_sw = [p for p in VAGUE_PHRASES_SW if p in low]

    if fabricated:
        verdict = "FABRICATED"
    elif verified:
        verdict = "GROUNDED"
    else:
        verdict = "WEAK"

    return {
        "verdict": verdict,
        "exportable": verdict == "GROUNDED",
        "verbatim_quotes_verified": verified,
        "verbatim_quotes_fabricated": fabricated,
        "vague_phrases_en": vague_en,
        "vague_phrases_sw": vague_sw,
        "lexical_overlap": round(lexical_overlap(report, context), 3),
        "words": len(report.split()),
    }
