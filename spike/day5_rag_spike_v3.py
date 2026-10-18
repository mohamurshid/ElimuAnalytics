"""
Day 5 (hardened): RAG spike on REAL KICD curriculum content.

This is a stricter version of day5_rag_spike_real.py. The original test asked
the retriever to match the query "3.0 Force and Energy 3.3 Heat Transfer"
against a chunk whose first two lines are literally
"STRAND: Force and Energy. SUB-STRAND: Heat transfer." That test cannot fail,
so passing it proves almost nothing. This version tests what the deployed
system will actually face.

WHAT IT TESTS
  A. Retrieval robustness   - 24 queries (3 phrasings x 8 sub-strands):
                              heading / teacher-described gap / failed quiz item.
                              Reports top-1 accuracy and top1-top2 margin.
  B. Hard negatives         - Heat Transfer vs Sound Energy and Floating and
                              Sinking, which share the same parent strand.
  C. Cross-chunk contamination
                            - With top_k=2 the prompt also carries a second
                              sub-strand. Does the report cite activities from
                              the WRONG chunk?
  D. Generation grounding   - 7 conditions: loose-prompt English, STRICT
                              verbatim-citation English, Kiswahili on Haiku 5.5,
                              Kiswahili on Sonnet 5.5, NO context (ablation),
                              WRONG context (plants for a heat-transfer learner),
                              and STRICT plus the item-level failure pattern.
                              5 and 6 are controls with known-correct answers
                              and print PASS/FAIL; the rest report a verdict and
                              are compared against each other.

WHAT CHANGED IN v3 (after the first real run)
  The v2 run scored the NO-CONTEXT ablation as GROUNDED - same three anchors as
  the grounded condition - because "conduction", "convection" and "radiation"
  are general science vocabulary the model produces unprompted. The measurement
  was broken, not the system. v3 therefore:
    - splits anchors into DISTINCTIVE (KICD-only phrases such as "oven gloves",
      "fireless cooker") and GENERIC (domain vocabulary that proves nothing);
      only distinctive phrases and verified verbatim quotes earn a pass
    - adds verbatim-quote checking, with a FABRICATED verdict for any quoted
      span that does not appear in the supplied context
    - adds a strict prompt that requires the KICD activity to be quoted verbatim,
      run alongside the loose prompt so the effect of the wording is isolated
    - applies a similarity floor before a second chunk enters the prompt (the
      v2 run admitted a plants chunk at 0.133 against the target's 0.355)
    - adds a Sonnet arm for the Kiswahili report, because Haiku's Kiswahili in
      the v2 run was not fit to send to a teacher

WHAT CHANGED IN v3.1 (model refresh, October 2026)
  The September run used claude-haiku-4-5 and claude-sonnet-4-5. Both have since
  moved: claude-sonnet-4-5-20250929 was deprecated on 30 Sept 2026 and retires on
  30 Nov 2026, and claude-haiku-4-5-20251001 carries a retirement date of "not
  sooner than 15 Oct 2026". Building the report generator on either one would mean
  rewriting it mid-submission, so the instrument now runs against claude-haiku-5-5
  and claude-sonnet-5-5. Nothing else about the measurement changed - same queries,
  same anchors, same grounding checker, same six conditions - so the September
  transcript and this one are directly comparable on grounding.

  Two warnings about the COST comparison, which is not directly comparable:
    - the per-token prices differ (Haiku 5.5 is an order of magnitude cheaper than
      Haiku 4.5 at $0.10/$0.50 per MTok against $1.00/$5.00), and
    - models from 4.7 onwards use a tokenizer that produces roughly 30% more
      tokens for the same text, so the token counts in the transcript are not on
      the same scale as September's either.
  Compare the dollar figure, not the token counts, and quote the dollar figure
  from the newest run rather than the 1.19 cents reported in September.

  The first v3.1 run then crashed on `'ThinkingBlock' object has no attribute
  'text'`, which exposed something the script had been assuming. From Claude 4.7
  onwards thinking is ADAPTIVE and cannot be switched off - the model decides per
  request, `thinking.budget_tokens` is rejected outright, and effort is the only
  lever. Three consequences, all handled here:
    - a response is a LIST of blocks and the report is not reliably the first
      one, so the text blocks are selected by type and the thinking block is
      discarded rather than concatenated (scoring the model's scratch work would
      inflate every grounding number - the same error v2 made)
    - thinking tokens count against max_tokens, so the old 500-token ceiling
      could be spent entirely on thinking; the ceiling is now 4000 and both
      truncation and an empty response are detected and announced, because
      either one makes a grounding verdict meaningless rather than negative
    - thinking tokens are billed as output tokens, so they are reported
      separately; effort defaults to "low" as the closest available setting to
      September's non-thinking behaviour

  The 14 Oct run then exposed three more things, all fixed here:
    - the `dist` count was inflated by substring overlap. "good and poor
      conductors" and "poor conductors" are both anchors, so one mention scored
      two. Condition 1's printed dist=2 was really 1, which drops it below the
      two-anchor threshold - so the loose prompt was never GROUNDED, and the
      strict prompt is doing more work than the first run suggested. Anchors are
      now reduced to maximal matches before counting.
    - conditions 5 and 6 printed UNGROUNDED, which reads as failure when both
      are passes: condition 6 named the context mismatch and refused to
      recommend anything, leaking no plant content. Controls now carry an
      expected verdict and print PASS/FAIL; the measured conditions deliberately
      do not, because declaring the expected answer for the thing under
      measurement is circular.
    - both English conditions asked, unprompted, for the item-level breakdown
      the prompt was withholding. Condition 7 supplies it - the questions she
      got wrong and the distractor she chose for each - to test whether that
      turns "please review her scripts" into a named misconception.

USAGE
  pip install sentence-transformers anthropic numpy
  setx ANTHROPIC_API_KEY "sk-ant-..."      (reopen Command Prompt afterwards)
  python day5_rag_spike_v3.py

  python day5_rag_spike_v3.py --no-api          retrieval tests only, no cost
  python day5_rag_spike_v3.py --embedder tfidf  no sentence-transformers needed
  python day5_rag_spike_v3.py --selftest        verify the grounding checker itself
  python day5_rag_spike_v3.py --effort medium   more adaptive thinking (slower, dearer)

A failed CONTROL means the instrument is broken, not that the system performed
badly. Fix it before reading anything into the measured conditions.

Writes day5_results_<timestamp>.json and day5_transcript_<timestamp>.txt
next to the script. Output is pure ASCII so Windows cmd will not choke on it.

Requires kicd_curriculum_chunks.py in the same folder.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from collections import Counter
from pathlib import Path
from statistics import mean

import numpy as np

from kicd_curriculum_chunks import CURRICULUM_CHUNKS

# The production prompt, imported rather than copied. `app` lives under
# backend/, which is not on the path when this script runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.reports import MAX_WORDS, RUBRIC_LEVELS, LearnerFacts  # noqa: E402
from app.reports import build_prompt as production_prompt  # noqa: E402

# RUBRIC_LEVELS comes from production too, where it is derived from TIER_CUTS -
# the thresholds that actually decide a learner's tier - rather than being a
# second hand-written list that can disagree with them.

# Current as of 14 Oct 2026. The 4-5 generation this spike originally used is on
# its way out (sonnet-4-5 retires 30 Nov 2026; haiku-4-5 is dated "not sooner
# than 15 Oct 2026"), and a dissertation result about a retired model is a result
# about nothing. These two IDs are the unversioned aliases, which is deliberate
# for a spike - the point is to measure what a teacher would get today. Pin a
# dated snapshot before anything goes in front of real learners.
DEFAULT_MODEL = "claude-haiku-5-5"
COMPARISON_MODEL = "claude-sonnet-5-5"   # used only for the Kiswahili quality arm

# From Claude 4.7 onwards thinking is ADAPTIVE: the model decides per request
# whether to think and for how long, requests that set thinking.budget_tokens
# are rejected with a 400, and the documented controls do not include an
# off-switch. The only lever is effort. "low" is the closest available setting
# to the non-thinking behaviour the September run measured, which is what makes
# the two runs comparable; it is also the cheapest, because thinking tokens are
# billed as output tokens.
#
# Note what this means for the write-up: the system cannot promise a teacher
# that no thinking happens, only that it asks for little. Report the effort
# level alongside the grounding verdicts - it is part of the configuration that
# produced them.
DEFAULT_EFFORT = "low"

# 500 was enough when nothing but the report came out of the model. It is not
# enough now: thinking tokens count against max_tokens, so a 500-token ceiling
# can be spent entirely on thinking and return a truncated report or no report
# at all. A truncated report scores UNGROUNDED for a reason that has nothing to
# do with grounding, which would be a false finding, so the ceiling is generous
# and truncation is detected and reported rather than left to be discovered in
# the verdicts. Unused headroom costs nothing - billing is on actual tokens.
MAX_TOKENS = 4000

# Similarity gates for admitting a second chunk into the prompt (v3).
FLOOR_ABS = 0.25
FLOOR_REL = 0.50

# USD per million tokens (input, output). Checked against the published price
# list on 14 Oct 2026. The superseded 4-5 rows are kept so an old transcript can
# still be re-priced; the current run uses the 5-5 rows.
#
# Haiku 5.5 is priced in two bands - $0.10/$0.50 below 100K input tokens and
# $0.50/$2.50 above it. This spike's prompts are a few thousand tokens, so the
# low band is the honest figure to quote. If the corpus ever gets stuffed whole
# into a prompt, that stops being true.
PRICING = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4": (15.00, 75.00),
}

FAKE_LEARNER = {
    "name": "Chebet K.",
    "grade": "Grade 5",
    "strand": "3.0 Force and Energy",
    "sub_strand": "3.3 Heat Transfer",
    "theta": -1.8,
    "ability_tier": "Below expectation",
    "consecutive_flags": 2,
    "items_answered": 12,  # above the 10-item minimum established on Day 3
    "items_correct": 8,
    # v3.1 ADDITION. In the 14 Oct run both English conditions stopped and asked
    # for this, unprompted: "the item-level breakdown is not provided, so the
    # failing outcome cannot be confirmed". The system already stores it -
    # Response.selected_option records which distractor the learner chose - and
    # the prompt was withholding it. Condition 7 tests whether supplying it
    # turns "please review her scripts" into a named misconception.
    #
    # The pattern below is deliberately coherent rather than random: items 1-3
    # all show conductor and insulator INVERTED (outcome b), while item 4 is a
    # separate confusion between the modes of transfer (outcome a). A report
    # that reads the pattern should say so; one that cannot will fall back to
    # listing outcomes, which is what conditions 1 and 2 did.
    "failed_items": [
        {
            "question": "Which of these is the best conductor of heat?",
            "chose": "A cotton cloth",
            "correct": "A metal spoon",
        },
        {
            "question": "Why is the handle of a cooking pot covered with plastic?",
            "chose": "Because plastic carries heat away quickly",
            "correct": "Because plastic is a poor conductor of heat",
        },
        {
            "question": (
                "A metal cup and a clay cup are filled with equally hot water "
                "and left on a table. Which one cools faster?"
            ),
            "chose": "The clay cup",
            "correct": "The metal cup",
        },
        {
            "question": "Heat from the sun reaches the earth mainly by",
            "chose": "conduction",
            "correct": "radiation",
        },
    ],
}

TARGET_ID = "sci_3_3"

# ---------------------------------------------------------------------------
# A. Query set. Three phrasings per sub-strand.
#   heading - what the original script used; the chunk's own words.
#   teacher - how a teacher would describe the gap in the dashboard.
#   item    - the text of an assessment item the learner got wrong. These
#             deliberately avoid curriculum vocabulary ("heat transfer",
#             "conduction") to see whether retrieval survives without keyword
#             overlap.
# ---------------------------------------------------------------------------
QUERIES = {
    "sci_1_1": {
        "teacher": (
            "The learner cannot tell apart plants that produce flowers from those that do not, "
            "and cannot name the parts of a flower or say what each part does."
        ),
        "item": (
            "Look at the drawing of the plant. Name the part labelled A and state one thing it "
            "does for the plant. Does this plant produce seeds inside a fruit?"
        ),
    },
    "sci_1_2": {
        "teacher": (
            "The learner keeps grouping animals wrongly, calling a frog a reptile and a bat a bird, "
            "and cannot list features shared by animals that have a backbone."
        ),
        "item": (
            "An animal has moist skin, lays its eggs in water and lives both in water and on land. "
            "Which group does it belong to? Give one feature that supports your answer."
        ),
    },
    "sci_1_3": {
        "teacher": (
            "The learner cannot name the parts air passes through when we breathe in, and cannot "
            "state how to keep those parts healthy."
        ),
        "item": (
            "Arrange these in the order air passes through them when a person breathes in: "
            "lungs, nose, windpipe. State one way of keeping them healthy."
        ),
    },
    "sci_2_1": {
        "teacher": (
            "The learner cannot choose a suitable way of getting sand out of water, and cannot say "
            "which mixtures look uniform and which do not."
        ),
        "item": (
            "You are given a jar containing iron nails, sand and salt mixed together. Describe how "
            "you would get each one out on its own, naming the method used at each step."
        ),
    },
    "sci_2_2": {
        "teacher": (
            "The learner cannot say what makes the water in the river unsafe, and cannot name a way "
            "of making it safe for drinking at home."
        ),
        "item": (
            "Name two things that make water in a stream unsafe to drink, and describe one method "
            "used at home to make that water safe."
        ),
    },
    "sci_3_1": {
        "teacher": (
            "The learner insists that heavy things always go to the bottom, and cannot explain why a "
            "large metal boat stays on top of the water."
        ),
        "item": (
            "A stone goes to the bottom of a basin of water but a dry piece of wood of the same size "
            "stays on top. Give one reason for the difference and name one thing that affects it."
        ),
    },
    "sci_3_2": {
        "teacher": (
            "The learner cannot explain how a drum makes a noise and does not connect shaking or "
            "vibration with what the ear hears."
        ),
        "item": (
            "A learner plucks a tight string and a noise is heard. Explain how the noise is produced "
            "and state one effect of very loud noise on people."
        ),
    },
    "sci_3_3": {
        "teacher": (
            "The learner cannot explain why a metal spoon left in hot porridge becomes hot while a "
            "wooden one stays cool, and cannot say which materials are safe for holding hot pots."
        ),
        "item": (
            "A cooking pot is made of metal but its handle is covered with plastic. Explain why the "
            "handle is made of a different material, and name a material that would keep food warm "
            "for longer."
        ),
    },
}

# ---------------------------------------------------------------------------
# C/D. Grounding anchors. Distinctive phrases that appear ONLY in one chunk's
# Suggested Learning Experiences / Projects. If a report contains the target
# chunk's anchors, it is quoting real KICD content. If it contains another
# chunk's anchors, the top_k window leaked. If it contains none, the model is
# writing from its own general knowledge, not the curriculum.
# ---------------------------------------------------------------------------
#   v3 CHANGE. In the v2 run the no-context ablation scored GROUNDED with the
#   same three anchors as the grounded condition, because "conduction",
#   "convection" and "radiation" are general science vocabulary the model
#   already knows. Counting those as evidence of curriculum grounding was a
#   broken measurement. Anchors are now split: only DISTINCTIVE phrases -
#   things that appear in KICD's document and essentially nowhere else -
#   decide the verdict. GENERIC terms are still counted, but reported
#   separately and treated as proving nothing.
ANCHORS = {
    "sci_1_1": ["flowering and non-flowering", "take a walk", "draw a flower and label"],
    "sci_1_2": ["portfolio", "mammals, birds, reptiles", "school compound"],
    "sci_1_3": ["models of the human breathing system", "print and non-print"],
    "sci_2_1": ["winnowing", "sieving", "decanting", "separating funnel"],
    "sci_2_2": ["water filters", "solar treatment", "water borne"],
    "sci_3_1": ["life savers", "lifesavers", "floaters", "buoy", "surfing"],
    "sci_3_2": ["sound producing instrument", "scratch", "vibrating strings", "vibrating drums"],
    "sci_3_3": [
        "oven gloves",
        "fireless cooker",
        "good and poor conductors",
        "poor conductors",
        "locally available materials",
    ],
}

# Domain vocabulary any competent model produces unprompted. Present in the
# curriculum text, but NOT evidence that the curriculum was used.
GENERIC_TERMS = {
    "sci_3_3": ["conduction", "convection", "radiation", "safety precautions", "insulation"],
    "sci_1_1": ["photosynthesis", "petal", "stamen"],
    "sci_2_1": ["filtering", "magnet", "evaporation"],
}

# Advice that is not grounded in anything. If these show up, RAG added nothing.
VAGUE_PHRASES = [
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

STOPWORDS = set(
    """the a an and or of to in for on with is are was were be been being this that these those
    it its as at by from into their there they them he she his her learner learners teacher class
    should would could can will has have had not no but if then than so such very more most other
    which who whom what when where how also may might must about over under between during each""".split()
)


# ---------------------------------------------------------------------------
# Output tee - everything printed also lands in the transcript file.
# ---------------------------------------------------------------------------
class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)

    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()

    def close(self):
        self.f.close()


def hr(title=""):
    print("\n" + "=" * 74)
    if title:
        print(title)
        print("=" * 74)


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------
class MiniLMEmbedder:
    """The production embedder: all-MiniLM-L6-v2, as specified in Chapter 3."""

    name = "all-MiniLM-L6-v2 (sentence-transformers)"

    def __init__(self):
        from sentence_transformers import SentenceTransformer

        print("Loading all-MiniLM-L6-v2 (first run downloads ~90MB)...")
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def encode(self, texts):
        return np.asarray(
            self.model.encode(list(texts), normalize_embeddings=True), dtype=np.float64
        )


class TfidfEmbedder:
    """Dependency-free fallback. NOT the production embedder - it is a bag of
    words with no semantic understanding, so it will underperform MiniLM on
    paraphrased queries. Included so the retrieval harness can run on a machine
    without sentence-transformers, and so results can be compared."""

    name = "TF-IDF bag-of-words (fallback, NOT production)"

    def __init__(self, corpus):
        self.vocab = {}
        docs = [self._tok(t) for t in corpus]
        for d in docs:
            for w in set(d):
                self.vocab.setdefault(w, len(self.vocab))
        n = len(docs)
        df = np.zeros(len(self.vocab))
        for d in docs:
            for w in set(d):
                df[self.vocab[w]] += 1
        self.idf = np.log((1 + n) / (1 + df)) + 1.0

    @staticmethod
    def _tok(text):
        return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS]

    def encode(self, texts):
        out = np.zeros((len(texts), len(self.vocab)))
        for i, t in enumerate(texts):
            for w in self._tok(t):
                j = self.vocab.get(w)
                if j is not None:
                    out[i, j] += 1
        out *= self.idf
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def rank(query_vec, chunk_matrix):
    sims = chunk_matrix @ query_vec
    order = np.argsort(sims)[::-1]
    return order, sims


# ---------------------------------------------------------------------------
# Part A/B: retrieval
# ---------------------------------------------------------------------------
def run_retrieval_tests(embedder, chunk_matrix, top_k):
    ids = [c["id"] for c in CURRICULUM_CHUNKS]
    by_id = {c["id"]: c for c in CURRICULUM_CHUNKS}

    styles = ["heading", "teacher", "item"]
    results = {s: [] for s in styles}

    hr("PART A - RETRIEVAL ROBUSTNESS (24 queries, 3 phrasings x 8 sub-strands)")
    print("heading = the chunk's own wording (the original, near-tautological test)")
    print("teacher = how a teacher would describe the gap")
    print("item    = text of a failed quiz item, curriculum vocabulary avoided\n")

    for style in styles:
        print("-" * 74)
        print(f"STYLE: {style}")
        print("-" * 74)
        print(f"{'expected':<32}{'retrieved #1':<32}{'sim':>6}{'margin':>8}  ok")
        queries = []
        for cid in ids:
            if style == "heading":
                q = f"{by_id[cid]['strand']} {by_id[cid]['sub_strand']}"
            else:
                q = QUERIES[cid][style]
            queries.append(q)
        qm = embedder.encode(queries)

        for cid, qv, qtext in zip(ids, qm, queries):
            order, sims = rank(qv, chunk_matrix)
            top1, top2 = order[0], order[1]
            margin = float(sims[top1] - sims[top2])
            ok = ids[top1] == cid
            results[style].append(
                {
                    "expected": cid,
                    "query": qtext,
                    "retrieved": ids[top1],
                    "sim": float(sims[top1]),
                    "margin": margin,
                    "correct": bool(ok),
                    "runner_up": ids[top2],
                }
            )
            print(
                f"{by_id[cid]['sub_strand'][:30]:<32}"
                f"{by_id[ids[top1]]['sub_strand'][:30]:<32}"
                f"{sims[top1]:>6.3f}{margin:>8.3f}  {'OK' if ok else 'FAIL'}"
            )

        acc = sum(r["correct"] for r in results[style]) / len(ids)
        mean_margin = float(np.mean([r["margin"] for r in results[style]]))
        print(f"\n  top-1 accuracy: {acc*100:.1f}%   mean margin: {mean_margin:.3f}")

    hr("PART B - HARD NEGATIVES (same parent strand, 3.0 Force and Energy)")
    print("The realistic failure is not 'plants beat heat transfer'. It is a")
    print("neighbouring sub-strand under the SAME strand winning. Full ranking")
    print("for the flagged learner, using the quiz-item phrasing:\n")
    q = QUERIES[TARGET_ID]["item"]
    print(f"  query: {q}\n")
    qv = embedder.encode([q])[0]
    order, sims = rank(qv, chunk_matrix)
    full_ranking = []
    for pos, i in enumerate(order, 1):
        marker = "  <-- TARGET" if ids[i] == TARGET_ID else ""
        same_strand = CURRICULUM_CHUNKS[i]["strand"] == FAKE_LEARNER["strand"]
        tag = " [same strand]" if same_strand and ids[i] != TARGET_ID else ""
        print(f"    {pos}. {sims[i]:.3f}  {CURRICULUM_CHUNKS[i]['sub_strand']}{tag}{marker}")
        full_ranking.append(
            {"rank": pos, "id": ids[i], "sub_strand": CURRICULUM_CHUNKS[i]["sub_strand"],
             "sim": float(sims[i])}
        )

    naive = [CURRICULUM_CHUNKS[i] for i in order[:top_k]]
    naive_scores = [float(sims[i]) for i in order[:top_k]]

    hr(f"PART C - CROSS-CHUNK CONTAMINATION AND SIMILARITY FLOOR (top_k = {top_k})")
    print("Naive top_k, no floor:")
    for c, s in zip(naive, naive_scores):
        print(f"  [{s:.3f}] {c['sub_strand']}")
    extra = [c for c in naive if c["id"] != TARGET_ID]
    if extra:
        print(
            "  -> prompt also carries Suggested Learning Experiences for "
            + ", ".join(c["sub_strand"] for c in extra)
        )

    # v3: in the v2 run the second chunk admitted to the prompt scored 0.133
    # against the target's 0.355 - noise, and from an unrelated strand. A chunk
    # now has to clear an absolute floor AND a share of the top score to get in.
    top = naive_scores[0]
    keep = [
        (c, s)
        for c, s in zip(naive, naive_scores)
        if s >= max(FLOOR_ABS, FLOOR_REL * top) or c is naive[0]
    ]
    print(f"\nWith floor (abs {FLOOR_ABS}, rel {FLOOR_REL} x top = {FLOOR_REL*top:.3f}):")
    for c, s in keep:
        print(f"  [{s:.3f}] {c['sub_strand']}")
    dropped = [c["sub_strand"] for c in naive if c["id"] not in [k[0]["id"] for k in keep]]
    print(f"  dropped: {', '.join(dropped) if dropped else 'nothing'}")

    retrieved = [c for c, _ in keep]
    retrieved_scores = [s for _, s in keep]

    return {"per_style": results, "full_ranking": full_ranking}, retrieved, retrieved_scores


# ---------------------------------------------------------------------------
# Part D: prompts, generation, grounding checker
# ---------------------------------------------------------------------------
def facts_of(learner):
    """The spike's learner fixture, as the production prompt's own input type."""
    return LearnerFacts(
        name=learner["name"],
        grade=learner["grade"],
        strand=learner["strand"],
        sub_strand=learner["sub_strand"],
        theta=learner["theta"],
        tier=learner["ability_tier"],
        items_answered=learner["items_answered"],
        consecutive_flags=learner["consecutive_flags"],
    )


def failure_pattern_of(learner):
    """The fixture as repository.learner_failure_pattern would return it.

    `unreported_failures` is 0 because every failed item in the fixture has
    both the chosen option and the key. In production that count is the number
    of wrong answers that cannot be described - hand-marked items - and the
    prompt says so rather than leaving the gap silent.
    """
    return {
        "answered": learner["items_answered"],
        "correct": learner["items_correct"],
        "failed_items": learner["failed_items"],
        "unreported_failures": 0,
    }


def build_prompt(learner, retrieved, language="English", strict=False, items=False):
    """The PRODUCTION prompt, assembled from this spike's fixtures.

    This file carried its own copy of the prompt until 18 October, and the
    copy had drifted: production states the five- and ten-item evidence
    thresholds, forbids gendered pronouns (added after the first live report
    said "She answered 12 items" about a learner whose sex the system does not
    know), allows 250 words rather than 200, and names the learner's actual
    grade instead of hard-coding Grade 5. Every grounding figure this script
    produced therefore described a prompt that is not the one being shipped,
    and it would have gone on passing while the two drifted further apart.

    The same fault, in a different place, cost a morning on 17 October: an
    instrument that holds a copy of the thing under test reports on the copy.

    Conditions 1 and 2 now differ by exactly one variable - the verbatim
    citation requirement - because both are built here with strict=False and
    strict=True. That is a cleaner comparison than before, when the loose
    condition was a whole separate prompt, but it does mean condition 1's
    recorded verdict from the 14 October run is not comparable with this one.
    Condition 5 keeps its own prompt below: production has no no-context
    variant, because refusing to generate without curriculum is the point.
    """
    return production_prompt(
        facts_of(learner),
        [c["text"] for c in retrieved],
        language=language,
        strict=strict,
        failure_pattern=failure_pattern_of(learner) if items else None,
    )


def build_prompt_no_context(learner):
    """Ablation: same task, no curriculum. Shows what RAG is actually adding.

    The word limit is production's, not a literal 200. An ablation has to
    differ from the conditions it is compared against by ONE thing - the
    curriculum context - and a different length budget would be a second.
    """
    tiers = ", ".join(RUBRIC_LEVELS)
    return f"""You are an educational advisor writing a diagnostic report for a Kenyan primary school teacher.

LEARNER PERFORMANCE:
- Learner: {learner['name']}, {learner['grade']}
- Strand: {learner['strand']}
- Sub-strand: {learner['sub_strand']}
- Estimated ability (IRT theta): {learner['theta']}
- KICD rubric level: {learner['ability_tier']}
- Flagged as at-risk for {learner['consecutive_flags']} consecutive assessments

The KICD rubric levels are: {tiers}

Write a 3-paragraph report addressed to the class teacher:
Paragraph 1: Summarise the learner's current standing against the KICD rubric level.
Paragraph 2: Identify the specific gap.
Paragraph 3: Recommend ONE concrete classroom activity.

Use clear, professional English. Maximum {MAX_WORDS} words."""


def verbatim_quotes(report, context_chunk_ids, min_words=5):
    """v3 addition. Pulls every quoted span out of the report and checks whether
    it actually occurs in the curriculum text supplied. A quoted span that is
    NOT in the context is a fabricated citation - the worst possible failure,
    because it looks like evidence."""
    ctx = " ".join(
        c["text"] for c in CURRICULUM_CHUNKS if c["id"] in context_chunk_ids
    ).lower()
    ctx = re.sub(r"\s+", " ", ctx)
    found, fabricated = [], []
    for q in re.findall(r'"([^"]{10,300})"', report) + re.findall(r"“([^”]{10,300})”", report):
        norm = re.sub(r"\s+", " ", q.lower().strip(" .;:,"))
        if len(norm.split()) < min_words:
            continue
        (found if norm in ctx else fabricated).append(q)
    return found, fabricated


def maximal(hits):
    """Drop any hit that is a proper substring of another hit.

    v3.1 FIX. The anchor list for Heat Transfer contains both
    "good and poor conductors" and "poor conductors", so a report using the
    longer phrase once scored TWO distinctive anchors for one mention. That
    inflated the `dist` column - the number that decides the verdict and the
    number that would have gone into the write-up. The 14 Oct run printed
    dist=2 for condition 1 where the honest count is 1.

    The shorter form is kept in ANCHORS deliberately: a report may well say
    only "poor conductors", and that should still count. It is the
    double-counting that is wrong, not the entry.

    If a report genuinely uses both phrasings in different places this
    under-counts by one. That is the safe direction for a grounding claim -
    it can only make the evidence look weaker than it is. Spelling variants
    that are not substrings of each other ("life savers" / "lifesavers") are
    unaffected, which is why this is substring-based and not fuzzy.
    """
    return [h for h in hits if not any(h != o and h in o for o in hits)]


def check_grounding(report, target_id, context_chunk_ids):
    """Counts genuine KICD anchors, wrong-chunk anchors, and vague filler."""
    low = report.lower()
    target_hits = maximal([a for a in ANCHORS[target_id] if a in low])
    generic_hits = maximal([g for g in GENERIC_TERMS.get(target_id, []) if g in low])
    quoted_ok, quoted_fabricated = verbatim_quotes(report, context_chunk_ids)
    other_hits = []
    for cid, anchors in ANCHORS.items():
        if cid == target_id:
            continue
        # Deduplicated per chunk, then labelled, so the cid prefix cannot
        # defeat the substring test.
        for a in maximal([a for a in anchors if a in low]):
            other_hits.append(f"{cid}:{a}")
    vague_hits = maximal([p for p in VAGUE_PHRASES if p in low])

    # Lexical overlap with the context actually supplied.
    ctx = " ".join(
        c["text"] for c in CURRICULUM_CHUNKS if c["id"] in context_chunk_ids
    ).lower()
    ctx_words = set(re.findall(r"[a-z]{5,}", ctx))
    rep_words = [w for w in re.findall(r"[a-z]{5,}", low) if w not in STOPWORDS]
    overlap = (
        sum(1 for w in rep_words if w in ctx_words) / len(rep_words) if rep_words else 0.0
    )

    # v3 verdict. Only DISTINCTIVE anchors and verified verbatim quotes count.
    # Generic domain vocabulary is recorded but never earns a pass, because the
    # v2 ablation proved the model produces it with no curriculum at all.
    evidence = len(target_hits) + len(quoted_ok)
    if quoted_fabricated:
        verdict = "FABRICATED"
    elif other_hits:
        # LEAKED means wording distinctive to another chunk APPEARS. It cannot
        # tell use from mention, and a correct refusal mentions the wrong
        # curriculum on purpose - naming what it is declining to use is the
        # most transparent answer available. Read it with the verified quotes
        # beside it: wording plus a verified quote is the wrong curriculum
        # being recommended; wording alone is usually a refusal explaining
        # itself.
        verdict = "LEAKED"
    elif evidence >= 2 and not vague_hits:
        verdict = "GROUNDED"
    elif evidence >= 1 and not vague_hits:
        verdict = "WEAK"
    elif evidence and vague_hits:
        verdict = "MIXED"
    else:
        verdict = "UNGROUNDED"

    return {
        "verdict": verdict,
        "target_anchors": target_hits,
        "generic_terms": generic_hits,
        "verbatim_quotes_verified": quoted_ok,
        "verbatim_quotes_fabricated": quoted_fabricated,
        "wrong_chunk_anchors": other_hits,
        "vague_phrases": vague_hits,
        "context_overlap": round(overlap, 3),
        "words": len(report.split()),
    }


def price(model, usage):
    # Longest prefix wins. "claude-sonnet-5" is a prefix of "claude-sonnet-5-5",
    # so first-match-in-dict-order would silently price the wrong model the
    # moment another row is added.
    key = max(
        (k for k in PRICING if model.startswith(k)), key=len, default=None
    )
    if key is None:
        return None
    pin, pout = PRICING[key]
    return usage.input_tokens / 1e6 * pin + usage.output_tokens / 1e6 * pout


def report_text(resp):
    """The report, and only the report.

    A response is a LIST of blocks and the first one is not necessarily the
    text: on an adaptive-thinking model it is often a ThinkingBlock, which is
    what crashed the first v3.1 run with
    `'ThinkingBlock' object has no attribute 'text'`.

    Thinking is deliberately excluded rather than concatenated. It is the
    model's scratch work: it is never shown to a teacher, so it is not part of
    the artefact under test, and feeding it to the grounding checker would
    score the scratch work instead of the report. Scratch work quotes the
    context freely while reasoning, so including it would inflate every
    grounding score - the same class of measurement error that v2 made.
    """
    return "\n".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()


def thinking_tokens(usage):
    """How many of the billed output tokens were internal reasoning, or None."""
    details = getattr(usage, "output_tokens_details", None)
    return getattr(details, "thinking_tokens", None) if details else None


def call_claude(client, model, prompt, label, effort=DEFAULT_EFFORT):
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": prompt}],
    )
    text = report_text(resp)
    cost = price(model, resp.usage)
    think = thinking_tokens(resp.usage)
    truncated = resp.stop_reason == "max_tokens"

    print(f"\n{'-'*74}\n{label}\n{'-'*74}")
    print(text if text else "(no text block in the response)")

    meta = f"{resp.usage.input_tokens} in / {resp.usage.output_tokens} out"
    if think is not None:
        meta += f" (of which {think} thinking)"
    meta += f" | effort={effort} | stop={resp.stop_reason}"
    meta += f" | ${cost:.6f}" if cost is not None else " | pricing unknown"
    print(f"\n[{meta}]")

    # Loud, because both of these invalidate the verdict rather than inform it.
    if truncated:
        print("  !! TRUNCATED at max_tokens. This report is incomplete and its")
        print("  !! grounding verdict is not evidence about grounding. Raise")
        print("  !! MAX_TOKENS and rerun before quoting anything from it.")
    if not text:
        print("  !! NO TEXT BLOCK. The model returned thinking and nothing else.")
        print("  !! Lower the effort or raise MAX_TOKENS; do not report this run.")

    return {
        "label": label,
        "text": text,
        "model": model,
        "effort": effort,
        "stop_reason": resp.stop_reason,
        "truncated": truncated,
        "empty": not text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "thinking_tokens": think,
        "cost_usd": cost,
    }


# ---------------------------------------------------------------------------
# Self-test of the grounding checker (no API, no embeddings)
# ---------------------------------------------------------------------------
def selftest():
    grounded = (
        "Chebet K. is performing at the Below expectation level on Heat Transfer. She cannot yet "
        "classify good and poor conductors of heat or demonstrate conduction, convection and "
        "radiation. I recommend the KICD project in which learners make oven gloves using locally "
        "available materials, alongside a discussion of safety precautions when handling heat."
    )
    vague = (
        "Chebet K. is below expectation. She struggles with the topic and needs support. "
        "I recommend extra practice and more attention during lessons, with one-on-one time."
    )
    leaked = (
        "Chebet K. is below expectation on heat transfer. Have learners make a sound producing "
        "instrument from locally available materials and create a sound game using Scratch."
    )
    # v3: the case the v2 checker got wrong. This is what the no-context
    # ablation actually produced - fluent, correct, and entirely invented.
    generic_only = (
        "Chebet K. is below expectation on Heat Transfer. She does not yet distinguish "
        "conduction, convection and radiation. Set up three stations: touching warm metal "
        "and wood, observing rising steam, and feeling warmth from a lamp, with a "
        "structured worksheet for recording observations."
    )
    fabricated = (
        "Chebet K. is below expectation. The curriculum suggests that learners should "
        '"construct a solar water heater from recycled bottles and measure its temperature '
        'rise over one hour", which I recommend running this week.'
    )
    ctx = ["sci_3_3", "sci_3_2"]
    cases = [
        ("grounded", grounded, "GROUNDED"),
        ("vague", vague, "UNGROUNDED"),
        ("leaked", leaked, "LEAKED"),
        ("generic", generic_only, "UNGROUNDED"),
        ("fabricated", fabricated, "FABRICATED"),
    ]
    ok = True
    for name, text, expected in cases:
        r = check_grounding(text, "sci_3_3", ctx)
        good = r["verdict"] == expected
        ok = ok and good
        print(f"  {name:<10} verdict={r['verdict']:<12} expected={expected:<12} "
              f"{'OK' if good else 'FAIL'}")
        print(f"             distinctive={r['target_anchors']} generic={r['generic_terms']}")
        print(f"             wrong_chunk={r['wrong_chunk_anchors']} vague={r['vague_phrases']}")
        print(f"             overlap={r['context_overlap']}")
    print("\n  Checker self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
def run_condition(client, label, prompt, cids, mdl, expect, effort):
    """One call, checked and printed. Returns the generation record.

    Lifted out of main's loop when --repeat arrived: the same condition now
    runs N times and the body cannot live inside the loop that repeats it.
    """
    gen = call_claude(client, mdl, prompt, label, effort=effort)
    gen["grounding"] = check_grounding(gen["text"], TARGET_ID, cids)
    g = gen["grounding"]

    # A control's result is only meaningful if the call itself was sound, so
    # truncation or an empty body fails it outright.
    gen["is_control"] = expect is not None
    if expect is None:
        gen["passed"] = None
    else:
        # Forbidden outcomes, not permitted ones. Both controls were written
        # with allow-lists of verdicts and both failed on a verdict that was
        # correct but not listed - a refusal scoring WEAK, an ablation
        # scoring FABRICATED. An allow-list has to anticipate every
        # acceptable outcome; a forbid-list only has to name the failure, and
        # the failure is the thing we actually understand.
        gen["passed"] = (
            g["verdict"] not in expect.get("forbid_verdicts", ())
            and not (expect.get("no_leak") and g["wrong_chunk_anchors"])
            and not (
                expect.get("no_verified_quotes") and g["verbatim_quotes_verified"]
            )
            and not (expect.get("no_distinctive") and g["target_anchors"])
            and not gen["truncated"]
            and not gen["empty"]
        )

    if expect is None:
        wanted = ""
    elif expect.get("forbid_verdicts"):
        requirement = (
            "must not quote the wrong curriculum"
            if expect.get("no_verified_quotes")
            else "must not leak or recommend"
        )
        wanted = (
            f" - must not be {' or '.join(expect['forbid_verdicts'])}, "
            f"{requirement}"
        )
    else:
        wanted = " - must not leak or recommend"
    print(f"  verdict: {g['verdict']}"
          + ("" if expect is None else
             f"   [CONTROL: {'PASS' if gen['passed'] else 'FAIL'}{wanted}]"))
    if expect is not None and not gen["passed"]:
        print(f"  why this control exists: {expect['why']}")
    print(f"  DISTINCTIVE KICD anchors (count as evidence): {g['target_anchors'] or 'none'}")
    print(f"  generic science terms (prove nothing):        {g['generic_terms'] or 'none'}")
    print(f"  verbatim quotes verified in context:          {g['verbatim_quotes_verified'] or 'none'}")
    print(f"  verbatim quotes NOT in context (fabricated):  {g['verbatim_quotes_fabricated'] or 'none'}")
    print(f"  wrong-chunk anchors: {g['wrong_chunk_anchors'] or 'none'}")
    print(f"  vague phrases: {g['vague_phrases'] or 'none'}")
    print(f"  lexical overlap with supplied context: {g['context_overlap']}")
    return gen


# Worst first, so one FABRICATED in five cannot hide behind four GROUNDEDs.
VERDICT_ORDER = ["FABRICATED", "UNGROUNDED", "WEAK", "MIXED", "GROUNDED"]


def tally(generations):
    """Per condition, in the order they were first run: what happened, N times.

    Keyed by label and ordered by first appearance rather than sorted, so the
    summary reads in the same order as the conditions themselves - 1 through
    7 - whatever the repeat count.
    """
    order, by_label = [], {}
    for gen in generations:
        label = gen["label"]
        if label not in by_label:
            order.append(label)
            by_label[label] = []
        by_label[label].append(gen)
    return [(label, by_label[label]) for label in order]


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default=DEFAULT_EFFORT,
        help="adaptive-thinking effort; there is no off-switch on 4.7+ models",
    )
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--no-api", action="store_true", help="retrieval tests only")
    ap.add_argument("--embedder", choices=["minilm", "tfidf"], default="minilm")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="run Part D N times and report counts instead of single verdicts",
    )
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    here = os.path.dirname(os.path.abspath(__file__))
    tee = Tee(os.path.join(here, f"day5_transcript_{stamp}.txt"))
    sys.stdout = tee

    try:
        print("ELIMU ANALYTICS - DAY 5 RAG SPIKE (hardened, v3.1 model refresh)")
        print(f"run: {datetime.now().isoformat(timespec='seconds')}")
        print(f"chunks: {len(CURRICULUM_CHUNKS)}  model: {args.model}  top_k: {args.top_k}")
        print(f"kiswahili comparison model: {COMPARISON_MODEL}")
        print(f"effort: {args.effort}  max_tokens: {MAX_TOKENS}")

        texts = [c["text"] for c in CURRICULUM_CHUNKS]
        if args.embedder == "minilm":
            embedder = MiniLMEmbedder()
        else:
            embedder = TfidfEmbedder(texts)
            print("\n!! Using the TF-IDF fallback. These numbers are NOT the")
            print("!! production retriever's numbers. Rerun with --embedder minilm.")
        print(f"embedder: {embedder.name}")
        chunk_matrix = embedder.encode(texts)

        retrieval, retrieved, retrieved_scores = run_retrieval_tests(
            embedder, chunk_matrix, args.top_k
        )

        results = {
            "run": stamp,
            "embedder": embedder.name,
            "model": args.model,
            "comparison_model": COMPARISON_MODEL,
            "effort": args.effort,
            "max_tokens": MAX_TOKENS,
            "top_k": args.top_k,
            "learner": FAKE_LEARNER,
            "retrieval": retrieval,
            "generations": [],
        }

        if args.no_api:
            hr("PART D SKIPPED (--no-api)")
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise SystemExit(
                    'ANTHROPIC_API_KEY not set.\nWindows: setx ANTHROPIC_API_KEY "sk-ant-..." '
                    "then reopen Command Prompt."
                )
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            ctx_ids = [c["id"] for c in retrieved]
            plants = [c for c in CURRICULUM_CHUNKS if c["id"] == "sci_1_1"]

            # Each condition carries an `expect`, and only the CONTROLS have one.
            #
            # v3.1: conditions 5 and 6 have known-correct answers, so they can
            # pass or fail. The 14 Oct run printed both as UNGROUNDED, which
            # reads as a failure when it is the opposite - condition 6 named the
            # mismatch and refused to recommend anything, leaking no plant
            # content, which is the single most important safety property here.
            #
            # Conditions 1-4 deliberately have expect=None. Declaring the
            # expected verdict for the thing being measured and then reporting
            # that it was met is circular; those conditions report a verdict and
            # the comparison BETWEEN them is the result.
            conditions = [
                ("1. MEASURED / EN / loose prompt (v2 wording)",
                 build_prompt(FAKE_LEARNER, retrieved, "English", strict=False),
                 ctx_ids, args.model, None),
                ("2. MEASURED / EN / STRICT verbatim-citation prompt",
                 build_prompt(FAKE_LEARNER, retrieved, "English", strict=True),
                 ctx_ids, args.model, None),
                ("3. MEASURED / KISWAHILI / Haiku 5.5",
                 build_prompt(FAKE_LEARNER, retrieved, "Kiswahili", strict=True),
                 ctx_ids, args.model, None),
                ("4. MEASURED / KISWAHILI / Sonnet 5.5 (quality comparison)",
                 build_prompt(FAKE_LEARNER, retrieved, "Kiswahili", strict=True),
                 ctx_ids, COMPARISON_MODEL, None),
                # Stated as what must NOT happen. This control allowed
                # ("UNGROUNDED", "MIXED") until 18 October and then failed on
                # FABRICATED - which is not a worse outcome than UNGROUNDED
                # here, it is a stronger one: with no context, any quoted span
                # of five or more words is unverifiable by construction, so a
                # report that happens to quote a phrase scores FABRICATED and
                # one that happens not to scores UNGROUNDED. The same prompt
                # produced both on consecutive runs.
                #
                # What must not happen is the checker CLAIMING grounding when
                # nothing was supplied to ground against - GROUNDED or WEAK -
                # or crediting distinctive KICD phrasing the model produced
                # from its own memory, which is precisely the v2 bug.
                ("5. CONTROL - NO CURRICULUM CONTEXT (ablation)",
                 build_prompt_no_context(FAKE_LEARNER), [], args.model,
                 {"forbid_verdicts": ("GROUNDED", "WEAK"),
                  "no_leak": True, "no_distinctive": True,
                  "why": "with no curriculum supplied, nothing can be grounded; "
                         "a GROUNDED or WEAK verdict, or a distinctive KICD "
                         "anchor, means the checker is crediting the model's "
                         "own knowledge, which is the v2 bug"}),
                # No `verdicts` key, deliberately. This control passed on a
                # verdict label until 18 October, when the model did exactly
                # the right thing and the control failed anyway: it refused,
                # recommended nothing, leaked no plant content - and quoted
                # the wrong chunk's own strand name while NAMING the mismatch
                # ("the retrieved material covers Living Things and their
                # Environment"). The checker counted that as a verified
                # citation, which lifts UNGROUNDED to WEAK, and the label
                # test failed a correct refusal.
                #
                # The label was always a proxy. What this control exists to
                # protect is that no plant activity reaches a teacher, and
                # that shows up as anchors, not as a verdict: target_anchors
                # empty means nothing distinctive was recommended,
                # wrong_chunk_anchors empty means nothing leaked. The verdict
                # is still printed, because it is informative - a refusal
                # scoring WEAK is worth knowing about - but it no longer
                # decides.
                ("6. CONTROL - WRONG CONTEXT (plants for a heat learner)",
                 build_prompt(FAKE_LEARNER, plants, "English", strict=True),
                 ["sci_1_1"], args.model,
                 # Third revision of this control, and the same lesson each
                 # time. It tested the verdict label, which failed a refusal
                 # that scored WEAK. It then tested wrong-chunk anchors,
                 # which failed a refusal that NAMED the plants outcomes in
                 # order to explain why they could not be used - "the
                 # Specific Learning Outcomes provided (classifying plants as
                 # flowering and non-flowering...) therefore cannot be used
                 # to locate the learner's gap in heat transfer". Both were
                 # proxies for use, and both punished transparency.
                 #
                 # The sharp test is available here: the ONLY context
                 # supplied is the wrong chunk, so any verified verbatim
                 # quote is necessarily a quote of the wrong curriculum,
                 # while a mention inside a refusal carries none. Anchors are
                 # still printed, because a human should read them when they
                 # appear.
                 #
                 # Known limitation, for Chapter 6: a recommendation
                 # PARAPHRASED from the wrong chunk would carry no verified
                 # quote and would pass this control. The strict prompt
                 # requires a verbatim citation for any recommendation, so
                 # such a report would be violating the prompt in two ways at
                 # once, but the instrument would not catch it.
                 {"forbid_verdicts": ("GROUNDED", "WEAK"),
                  "no_verified_quotes": True, "no_distinctive": True,
                  "why": "the only safe answer is to refuse; a recommendation "
                         "built from plants curriculum for a heat learner would "
                         "be a wrong-chunk leak reaching a teacher"}),
                ("7. MEASURED / EN / STRICT + item-level failure pattern",
                 build_prompt(FAKE_LEARNER, retrieved, "English", strict=True, items=True),
                 ctx_ids, args.model, None),
            ]

            hr("PART D - GENERATION UNDER SEVEN CONDITIONS")
            print("1 vs 2 isolates the prompt wording; 3 vs 4 isolates the model;")
            print("2 vs 7 isolates the item-level failure pattern; 5 and 6 are")
            print("controls with known-correct answers and print PASS or FAIL.\n")
            if args.repeat > 1:
                print(f"{args.repeat} passes over every condition, same prompts "
                      f"each time.\nOne pass is an anecdote: across four runs of "
                      f"an unchanged prompt,\ncondition 1 came back GROUNDED, "
                      f"WEAK and UNGROUNDED, and condition 7\nfabricated a "
                      f"citation once. Counts, not samples.\n")

            for attempt in range(1, args.repeat + 1):
                if args.repeat > 1:
                    hr(f"PASS {attempt} OF {args.repeat}")
                for label, prompt, cids, mdl, expect in conditions:
                    gen = run_condition(
                        client, label, prompt, cids, mdl, expect, args.effort
                    )
                    gen["pass"] = attempt
                    results["generations"].append(gen)


            hr("SUMMARY")
            if args.repeat == 1:
                print(f"{'condition':<48}{'verdict':<12}{'dist':>5}{'quote':>6}"
                      f"{'gen':>5}{'vague':>7}{'  control':<10}")
                for gen in results["generations"]:
                    g = gen["grounding"]
                    if gen.get("empty"):
                        flag = "  <-- EMPTY, verdict not valid"
                    elif gen.get("truncated"):
                        flag = "  <-- TRUNCATED, verdict not valid"
                    elif gen["passed"] is True:
                        flag = "  PASS"
                    elif gen["passed"] is False:
                        flag = "  FAIL"
                    else:
                        flag = "  (measured)"
                    print(f"{gen['label'][:46]:<48}{g['verdict']:<12}"
                          f"{len(g['target_anchors']):>5}"
                          f"{len(g['verbatim_quotes_verified']):>6}"
                          f"{len(g['generic_terms']):>5}"
                          f"{len(g['vague_phrases']):>7}{flag}")
            else:
                # Counts, with the worst outcome first so a single FABRICATED
                # in five cannot hide behind four GROUNDEDs. dist and quote
                # are means across the passes.
                print(f"{'condition':<40}{'verdicts over ' + str(args.repeat) + ' passes':<42}"
                      f"{'dist':>5}{'quote':>6}  control")
                for label, runs in tally(results["generations"]):
                    counted = Counter(r["grounding"]["verdict"] for r in runs)
                    worst_first = sorted(
                        counted.items(),
                        key=lambda kv: VERDICT_ORDER.index(kv[0])
                        if kv[0] in VERDICT_ORDER else 0,
                    )
                    verdicts = ", ".join(f"{v} {n}" for v, n in worst_first)
                    dist = mean(len(r["grounding"]["target_anchors"]) for r in runs)
                    quote = mean(
                        len(r["grounding"]["verbatim_quotes_verified"]) for r in runs
                    )
                    if runs[0]["is_control"]:
                        ok = sum(1 for r in runs if r["passed"])
                        flag = f"  {'PASS' if ok == len(runs) else 'FAIL'} {ok}/{len(runs)}"
                    else:
                        flag = "  (measured)"
                    print(f"{label[:38]:<40}{verdicts[:40]:<42}"
                          f"{dist:>5.1f}{quote:>6.1f}{flag}")

            # Every pass, not most of them. A control that passes four times
            # in five is a broken control, and averaging it away is how an
            # instrument stops reporting its own failures.
            controls = [g for g in results["generations"] if g["is_control"]]
            ctl_ok = all(g["passed"] for g in controls)
            results["controls_passed"] = ctl_ok
            print(f"\nCONTROLS: {sum(1 for g in controls if g['passed'])}/"
                  f"{len(controls)} control runs passed."
                  + ("" if ctl_ok else
                     " A failed control invalidates the measured conditions -"
                     " fix it before quoting any of them."))
            print("\ndist  = distinctive KICD anchors, deduplicated (real evidence)")
            print("quote = verbatim citations verified against the supplied context")
            print("gen   = generic science vocabulary (the v2 false-positive source)")
            print("\nKISWAHILI REVIEW - read conditions 3 and 4 as a Kiswahili speaker, not")
            print("as a score. Check: is any phrasing demeaning about the child? Are the")
            print("technical terms the ones a Kenyan teacher uses? Is it fit to send home?")

            costs = [g["cost_usd"] for g in results["generations"] if g["cost_usd"]]
            total = sum(costs)
            # Selected by label. This was generations[1:3] - positional, and
            # adding condition 7 would silently have changed what "bilingual"
            # meant without changing the number's name.
            bilingual = sum(
                g["cost_usd"] for g in results["generations"]
                if g["cost_usd"] and g["label"].startswith(("2.", "3."))
            )
            # Divided by the pass count: `bilingual` sums conditions 2 and 3
            # across every pass, and the figure that means anything is the
            # cost of ONE report.
            per_report = bilingual / args.repeat
            print(f"\nTotal this run ({len(costs)} calls): ${total:.5f}")
            print(f"Bilingual report (EN strict + SW Haiku): ${per_report:.5f} "
                  f"= {per_report*100:.2f} cents"
                  + (f"  (mean of {args.repeat})" if args.repeat > 1 else ""))
            print(f"Projected 60 UAT bilingual reports: ${per_report*60:.2f}")
            think_total = sum(
                g["thinking_tokens"] or 0 for g in results["generations"]
            )
            out_total = sum(g["output_tokens"] for g in results["generations"])
            if out_total:
                print(f"Thinking tokens: {think_total} of {out_total} billed output "
                      f"tokens ({think_total / out_total * 100:.0f}%)")
            print("\nNOTE: this figure supersedes the 1.19 cents measured in September.")
            print("Different models at different prices, and a tokenizer from 4.7")
            print("onwards that emits ~30% more tokens for the same text. Quote this")
            print("number, and say which models produced it.")
            results["cost"] = {
                "run_total_usd": total,
                "bilingual_report_usd": per_report,
                "passes": args.repeat,
            }

        out = os.path.join(here, f"day5_results_{stamp}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        hr("PASTE THIS BACK")
        for style, rows in retrieval["per_style"].items():
            acc = sum(r["correct"] for r in rows) / len(rows) * 100
            mm = float(np.mean([r["margin"] for r in rows]))
            misses = [f"{r['expected']}->{r['retrieved']}" for r in rows if not r["correct"]]
            print(f"  retrieval {style:<8} top-1 {acc:5.1f}%  mean margin {mm:.3f}"
                  + (f"  misses: {', '.join(misses)}" if misses else ""))
        for label, runs in tally(results.get("generations", [])):
            if len(runs) == 1:
                g = runs[0]["grounding"]
                print(f"  {label[:44]:<46} {g['verdict']:<11} "
                      f"dist={len(g['target_anchors'])} "
                      f"quote={len(g['verbatim_quotes_verified'])} "
                      f"gen={len(g['generic_terms'])} "
                      f"vague={len(g['vague_phrases'])}")
            else:
                counted = Counter(r["grounding"]["verdict"] for r in runs)
                worst_first = sorted(
                    counted.items(),
                    key=lambda kv: VERDICT_ORDER.index(kv[0])
                    if kv[0] in VERDICT_ORDER else 0,
                )
                print(f"  {label[:44]:<46} "
                      + ", ".join(f"{v} {n}/{len(runs)}" for v, n in worst_first))
        if results.get("cost"):
            print(f"  cost this run: ${results['cost']['run_total_usd']:.5f}")
        print(f"\n  files: day5_results_{stamp}.json / day5_transcript_{stamp}.txt")
    finally:
        sys.stdout = sys.__stdout__
        tee.close()


if __name__ == "__main__":
    main()
