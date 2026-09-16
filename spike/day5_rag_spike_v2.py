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
  D. Generation grounding   - 4 conditions: grounded English, grounded
                              Kiswahili, NO context (ablation), WRONG context
                              (plants context for a heat-transfer learner).
                              An automated checker counts genuine KICD activity
                              anchors and vague-advice red flags in each.
  E. Cost                   - per-call and projected token cost.

USAGE
  pip install sentence-transformers anthropic numpy
  setx ANTHROPIC_API_KEY "sk-ant-..."      (reopen Command Prompt afterwards)
  python day5_rag_spike_v2.py

  python day5_rag_spike_v2.py --no-api          retrieval tests only, no cost
  python day5_rag_spike_v2.py --embedder tfidf  no sentence-transformers needed
  python day5_rag_spike_v2.py --selftest        verify the grounding checker itself
  python day5_rag_spike_v2.py --model claude-sonnet-4-5-20250929

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
ANCHORS = {
    "sci_1_1": ["flowering and non-flowering", "label parts", "take a walk", "draw a flower"],
    "sci_1_2": ["portfolio", "mammals, birds, reptiles", "school compound"],
    "sci_1_3": ["trachea", "diaphragm", "models of the human breathing system", "asthma"],
    "sci_2_1": ["winnowing", "sieving", "decanting", "separating funnel", "homogeneous"],
    "sci_2_2": ["water filters", "boiling", "solar treatment", "water borne"],
    "sci_3_1": ["life savers", "lifesavers", "floaters", "buoy", "surfing"],
    "sci_3_2": ["sound producing instrument", "scratch", "echo", "vibrating strings", "vibrating drums"],
    "sci_3_3": [
        "oven gloves",
        "fireless cooker",
        "good and poor conductors",
        "conduction",
        "convection",
        "radiation",
        "safety precautions",
    ],
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

    retrieved = [CURRICULUM_CHUNKS[i] for i in order[:top_k]]
    retrieved_scores = [float(sims[i]) for i in order[:top_k]]

    hr(f"PART C - CROSS-CHUNK CONTAMINATION RISK (top_k = {top_k})")
    for c, s in zip(retrieved, retrieved_scores):
        print(f"  in prompt: [{s:.3f}] {c['sub_strand']}")
    extra = [c for c in retrieved if c["id"] != TARGET_ID]
    if extra:
        print(
            "\n  The prompt therefore also contains Suggested Learning Experiences for "
            + ", ".join(c["sub_strand"] for c in extra)
        )
        print("  Part D checks whether the report cites activities from those chunks.")
    else:
        print("\n  Only the target chunk is in the prompt; no contamination possible.")

    return {"per_style": results, "full_ranking": full_ranking}, retrieved, retrieved_scores


# ---------------------------------------------------------------------------
# Part D: prompts, generation, grounding checker
# ---------------------------------------------------------------------------
def build_prompt(learner, retrieved, language="English"):
    context = "\n\n".join(c["text"] for c in retrieved)
    tiers = ", ".join(RUBRIC_LEVELS)
    lang_line = (
        "Use clear, professional English."
        if language == "English"
        else "Andika ripoti yote kwa Kiswahili sanifu. Write the entire report in standard Kiswahili."
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


def check_grounding(report, target_id, context_chunk_ids):
    """Counts genuine KICD anchors, wrong-chunk anchors, and vague filler."""
    low = report.lower()
    target_hits = [a for a in ANCHORS[target_id] if a in low]
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

    if len(target_hits) >= 2 and not vague_hits:
        verdict = "GROUNDED"
    elif target_hits and not vague_hits:
        verdict = "WEAK"
    elif target_hits and vague_hits:
        verdict = "MIXED"
    else:
        verdict = "UNGROUNDED"

    return {
        "verdict": verdict,
        "target_anchors": target_hits,
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
    ctx = ["sci_3_3", "sci_3_2"]
    cases = [("grounded", grounded, "GROUNDED"), ("vague", vague, "UNGROUNDED"),
             ("leaked", leaked, "UNGROUNDED")]
    ok = True
    for name, text, expected in cases:
        r = check_grounding(text, "sci_3_3", ctx)
        good = r["verdict"] == expected
        ok = ok and good
        print(f"  {name:<10} verdict={r['verdict']:<12} expected={expected:<12} "
              f"{'OK' if good else 'FAIL'}")
        print(f"             target_anchors={r['target_anchors']}")
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
                ("1. GROUNDED / ENGLISH", build_prompt(FAKE_LEARNER, retrieved, "English"), ctx_ids),
                ("2. GROUNDED / KISWAHILI", build_prompt(FAKE_LEARNER, retrieved, "Kiswahili"), ctx_ids),
                ("3. ABLATION - NO CURRICULUM CONTEXT", build_prompt_no_context(FAKE_LEARNER), []),
                ("4. CONTROL - WRONG CONTEXT (plants for a heat learner)",
                 build_prompt(FAKE_LEARNER, plants, "English"), ["sci_1_1"]),
            ]

            hr("PART D - GENERATION UNDER FOUR CONDITIONS")
            for label, prompt, cids in conditions:
                gen = call_claude(client, args.model, prompt, label)
                gen["grounding"] = check_grounding(gen["text"], TARGET_ID, cids)
                g = gen["grounding"]
                print(f"  grounding: {g['verdict']}  target_anchors={g['target_anchors']}")
                print(f"  wrong-chunk anchors: {g['wrong_chunk_anchors'] or 'none'}")
                print(f"  vague phrases: {g['vague_phrases'] or 'none'}")
                print(f"  lexical overlap with supplied context: {g['context_overlap']}")
                results["generations"].append(gen)

            hr("SUMMARY")
            print(f"{'condition':<48}{'verdict':<13}{'anchors':>8}{'vague':>7}")
            for gen in results["generations"]:
                g = gen["grounding"]
                print(f"{gen['label'][:46]:<48}{g['verdict']:<13}"
                      f"{len(g['target_anchors']):>8}{len(g['vague_phrases']):>7}")

            costs = [g["cost_usd"] for g in results["generations"] if g["cost_usd"]]
            total = sum(costs)
            bilingual = sum(
                g["cost_usd"] for g in results["generations"][:2] if g["cost_usd"]
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
            print(f"  {gen['label'][:44]:<46} {g['verdict']:<12} "
                  f"anchors={len(g['target_anchors'])} vague={len(g['vague_phrases'])}")
        if results.get("cost"):
            print(f"  cost this run: ${results['cost']['run_total_usd']:.5f}")
        print(f"\n  files: day5_results_{stamp}.json / day5_transcript_{stamp}.txt")
    finally:
        sys.stdout = sys.__stdout__
        tee.close()


if __name__ == "__main__":
    main()
