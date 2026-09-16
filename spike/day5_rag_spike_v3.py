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
  D. Generation grounding   - 6 conditions: loose-prompt English, STRICT
                              verbatim-citation English, Kiswahili on Haiku,
                              Kiswahili on Sonnet, NO context (ablation), and
                              WRONG context (plants for a heat-transfer learner).

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

USAGE
  pip install sentence-transformers anthropic numpy
  setx ANTHROPIC_API_KEY "sk-ant-..."      (reopen Command Prompt afterwards)
  python day5_rag_spike_v3.py

  python day5_rag_spike_v3.py --no-api          retrieval tests only, no cost
  python day5_rag_spike_v3.py --embedder tfidf  no sentence-transformers needed
  python day5_rag_spike_v3.py --selftest        verify the grounding checker itself

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

import numpy as np

from kicd_curriculum_chunks import CURRICULUM_CHUNKS, RUBRIC_LEVELS

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
COMPARISON_MODEL = "claude-sonnet-4-5"   # used only for the Kiswahili quality arm

# Similarity gates for admitting a second chunk into the prompt (v3).
FLOOR_ABS = 0.25
FLOOR_REL = 0.50

# USD per million tokens (input, output), Sept 2026.
PRICING = {
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
def build_prompt(learner, retrieved, language="English", strict=False):
    context = "\n\n".join(c["text"] for c in retrieved)
    tiers = ", ".join(RUBRIC_LEVELS)
    lang_line = (
        "Use clear, professional English."
        if language == "English"
        else (
            "Andika ripoti yote kwa Kiswahili sanifu kinachotumika shuleni Kenya. "
            "Write the entire report in the standard Kiswahili used in Kenyan schools. "
            "Use respectful language about the learner at all times; never use words "
            "that imply the child is stupid or ignorant. Where an accurate Kiswahili "
            "technical term does not exist, give the Kiswahili term followed by the "
            "English term in brackets rather than inventing a word."
        )
    )
    # v3: the v2 run produced paragraph 3 recommendations that paraphrased the
    # curriculum generically and never reached the distinctive KICD projects
    # ("make oven gloves using locally available materials"). Strict mode forces
    # an explicit verbatim citation so grounding becomes checkable rather than
    # a matter of opinion.
    strict_line = (
        "\nIn Paragraph 3 you MUST quote the chosen activity verbatim from the "
        "SUGGESTED LEARNING EXPERIENCES or PROJECTS above, inside double quotation "
        "marks, exactly as written, before explaining how the teacher should run it. "
        "Prefer a named PROJECT where one exists. Do not paraphrase the quoted part, "
        "and do not quote anything that is not in the context above.\n"
        if strict
        else ""
    )
    return f"""You are an educational advisor writing a diagnostic report for a Kenyan primary school teacher.

CURRICULUM CONTEXT (retrieved from the official KICD Grade 5 curriculum design):
{context}

LEARNER PERFORMANCE:
- Learner: {learner['name']}, {learner['grade']}
- Strand: {learner['strand']}
- Sub-strand: {learner['sub_strand']}
- Estimated ability (IRT theta): {learner['theta']}
- KICD rubric level: {learner['ability_tier']}
- Items answered in this sub-strand: {learner['items_answered']}
- Flagged as at-risk for {learner['consecutive_flags']} consecutive assessments

The KICD rubric levels are: {tiers}

Write a 3-paragraph report addressed to the class teacher:
Paragraph 1: Summarise the learner's current standing against the KICD rubric level.
Paragraph 2: Identify the specific gap, referencing the Specific Learning Outcomes
             from the curriculum context above.
Paragraph 3: Recommend ONE concrete classroom activity, drawn directly from the
             Suggested Learning Experiences in the curriculum context.
{strict_line}
{lang_line} Maximum 200 words. Do not invent curriculum content that is not
present in the context above. If the curriculum context does not cover this
learner's sub-strand, say so explicitly instead of writing a recommendation."""


def build_prompt_no_context(learner):
    """Ablation: same task, no curriculum. Shows what RAG is actually adding."""
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

Use clear, professional English. Maximum 200 words."""


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


def check_grounding(report, target_id, context_chunk_ids):
    """Counts genuine KICD anchors, wrong-chunk anchors, and vague filler."""
    low = report.lower()
    target_hits = [a for a in ANCHORS[target_id] if a in low]
    generic_hits = [g for g in GENERIC_TERMS.get(target_id, []) if g in low]
    quoted_ok, quoted_fabricated = verbatim_quotes(report, context_chunk_ids)
    other_hits = []
    for cid, anchors in ANCHORS.items():
        if cid == target_id:
            continue
        for a in anchors:
            if a in low:
                other_hits.append(f"{cid}:{a}")
    vague_hits = [p for p in VAGUE_PHRASES if p in low]

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
    key = next((k for k in PRICING if model.startswith(k)), None)
    if key is None:
        return None
    pin, pout = PRICING[key]
    return usage.input_tokens / 1e6 * pin + usage.output_tokens / 1e6 * pout


def call_claude(client, model, prompt, label):
    resp = client.messages.create(
        model=model, max_tokens=500, messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text
    cost = price(model, resp.usage)
    print(f"\n{'-'*74}\n{label}\n{'-'*74}")
    print(text)
    print(
        f"\n[{resp.usage.input_tokens} in / {resp.usage.output_tokens} out"
        + (f" | ${cost:.6f}]" if cost is not None else " | pricing unknown]")
    )
    return {
        "label": label,
        "text": text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
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
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--no-api", action="store_true", help="retrieval tests only")
    ap.add_argument("--embedder", choices=["minilm", "tfidf"], default="minilm")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    here = os.path.dirname(os.path.abspath(__file__))
    tee = Tee(os.path.join(here, f"day5_transcript_{stamp}.txt"))
    sys.stdout = tee

    try:
        print("ELIMU ANALYTICS - DAY 5 RAG SPIKE (hardened)")
        print(f"run: {datetime.now().isoformat(timespec='seconds')}")
        print(f"chunks: {len(CURRICULUM_CHUNKS)}  model: {args.model}  top_k: {args.top_k}")

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

            conditions = [
                ("1. GROUNDED / EN / loose prompt (v2 wording)",
                 build_prompt(FAKE_LEARNER, retrieved, "English", strict=False), ctx_ids, args.model),
                ("2. GROUNDED / EN / STRICT verbatim-citation prompt",
                 build_prompt(FAKE_LEARNER, retrieved, "English", strict=True), ctx_ids, args.model),
                ("3. GROUNDED / KISWAHILI / Haiku",
                 build_prompt(FAKE_LEARNER, retrieved, "Kiswahili", strict=True), ctx_ids, args.model),
                ("4. GROUNDED / KISWAHILI / Sonnet (quality comparison)",
                 build_prompt(FAKE_LEARNER, retrieved, "Kiswahili", strict=True), ctx_ids,
                 COMPARISON_MODEL),
                ("5. ABLATION - NO CURRICULUM CONTEXT",
                 build_prompt_no_context(FAKE_LEARNER), [], args.model),
                ("6. CONTROL - WRONG CONTEXT (plants for a heat learner)",
                 build_prompt(FAKE_LEARNER, plants, "English", strict=True), ["sci_1_1"], args.model),
            ]

            hr("PART D - GENERATION UNDER SIX CONDITIONS")
            print("Condition 1 vs 2 isolates the prompt change; 3 vs 4 isolates the model;")
            print("5 is the control that exposed the broken v2 measurement; 6 tests refusal.\n")
            for label, prompt, cids, mdl in conditions:
                gen = call_claude(client, mdl, prompt, label)
                gen["grounding"] = check_grounding(gen["text"], TARGET_ID, cids)
                g = gen["grounding"]
                print(f"  verdict: {g['verdict']}")
                print(f"  DISTINCTIVE KICD anchors (count as evidence): {g['target_anchors'] or 'none'}")
                print(f"  generic science terms (prove nothing):        {g['generic_terms'] or 'none'}")
                print(f"  verbatim quotes verified in context:          {g['verbatim_quotes_verified'] or 'none'}")
                print(f"  verbatim quotes NOT in context (fabricated):  {g['verbatim_quotes_fabricated'] or 'none'}")
                print(f"  wrong-chunk anchors: {g['wrong_chunk_anchors'] or 'none'}")
                print(f"  vague phrases: {g['vague_phrases'] or 'none'}")
                print(f"  lexical overlap with supplied context: {g['context_overlap']}")
                results["generations"].append(gen)

            hr("SUMMARY")
            print(f"{'condition':<48}{'verdict':<12}{'dist':>5}{'quote':>6}{'gen':>5}{'vague':>7}")
            for gen in results["generations"]:
                g = gen["grounding"]
                print(f"{gen['label'][:46]:<48}{g['verdict']:<12}"
                      f"{len(g['target_anchors']):>5}{len(g['verbatim_quotes_verified']):>6}"
                      f"{len(g['generic_terms']):>5}{len(g['vague_phrases']):>7}")
            print("\ndist  = distinctive KICD anchors (real evidence of grounding)")
            print("quote = verbatim citations verified against the supplied context")
            print("gen   = generic science vocabulary (the v2 false-positive source)")
            print("\nKISWAHILI REVIEW - read conditions 3 and 4 as a Kiswahili speaker, not")
            print("as a score. Check: is any phrasing demeaning about the child? Are the")
            print("technical terms the ones a Kenyan teacher uses? Is it fit to send home?")

            costs = [g["cost_usd"] for g in results["generations"] if g["cost_usd"]]
            total = sum(costs)
            bilingual = sum(
                g["cost_usd"] for g in results["generations"][1:3] if g["cost_usd"]
            )
            print(f"\nTotal this run ({len(costs)} calls): ${total:.5f}")
            print(f"Bilingual report (EN + SW): ${bilingual:.5f} = {bilingual*100:.2f} cents")
            print(f"Projected 60 UAT bilingual reports: ${bilingual*60:.2f}")
            results["cost"] = {"run_total_usd": total, "bilingual_report_usd": bilingual}

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
        for gen in results.get("generations", []):
            g = gen["grounding"]
            print(f"  {gen['label'][:44]:<46} {g['verdict']:<11} "
                  f"dist={len(g['target_anchors'])} quote={len(g['verbatim_quotes_verified'])} "
                  f"gen={len(g['generic_terms'])} vague={len(g['vague_phrases'])}")
        if results.get("cost"):
            print(f"  cost this run: ${results['cost']['run_total_usd']:.5f}")
        print(f"\n  files: day5_results_{stamp}.json / day5_transcript_{stamp}.txt")
    finally:
        sys.stdout = sys.__stdout__
        tee.close()


if __name__ == "__main__":
    main()
