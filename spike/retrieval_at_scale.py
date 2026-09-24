"""
Retrieval accuracy at full corpus scale.

The Day 5 spike measured 100% top-1 retrieval accuracy against 8 hand-extracted
Grade 5 Science chunks. That is a small pool: with eight candidates, a query
only has to beat seven competitors, most of them from unrelated strands. This
harness repeats the measurement against the full harvested curriculum - roughly
1,600 sub-strand chunks spanning six grades and thirteen learning areas - which
is the pool the deployed system will actually search.

FOUR TESTS

  A. Corpus-wide heading retrieval
     For a random sample of chunks, query with the chunk's own strand and
     sub-strand heading and check whether it ranks first. This is the easiest
     possible query, so it establishes a ceiling: whatever accuracy the system
     achieves here, realistic queries will be at or below it.

  B. Realistic phrasing on known sub-strands
     The Day 5 query set - teacher-described gaps and failed quiz items, with
     curriculum vocabulary deliberately avoided - now searching the whole
     corpus instead of eight candidates.

  C. Strand-level pre-filtering
     Test B repeated with candidates restricted to the learner's grade and
     learning area. Elimu Analytics always knows both, so this filter is free.
     The comparison quantifies what it is worth.

  D. Per-learning-area accuracy
     Test A broken down by learning area, to show whether any area retrieves
     materially worse than the rest.

USAGE
    python spike\\retrieval_at_scale.py
    python spike\\retrieval_at_scale.py --embedder tfidf   (no torch needed)
    python spike\\retrieval_at_scale.py --sample 500

Writes retrieval_at_scale_<timestamp>.json and .md next to the corpus.
Output is pure ASCII. No API calls, no cost.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

CORPUS = Path("data/kicd/kicd_curriculum_chunks_full.json")

STOPWORDS = set(
    """the a an and or of to in for on with is are was were be been being this that these those
    it its as at by from into their there they them he she his her learner learners teacher class
    should would could can will has have had not no but if then than so such very more most other
    which who whom what when where how also may might must about over under between during each""".split()
)

# The Day 5 query set, now pointed at the full corpus. Targets are located by
# grade + learning area + sub-strand prefix rather than by hardcoded chunk id,
# because ids change every time the corpus is rebuilt.
DAY5_QUERIES = [
    {
        "target": ("Grade 5", "Science and Technology", "1.1 Classification of plants"),
        "teacher": ("The learner cannot tell apart plants that produce flowers from those that "
                    "do not, and cannot name the parts of a flower or say what each part does."),
        "item": ("Look at the drawing of the plant. Name the part labelled A and state one thing "
                 "it does for the plant. Does this plant produce seeds inside a fruit?"),
    },
    {
        "target": ("Grade 5", "Science and Technology", "1.2 Vertebrates"),
        "teacher": ("The learner keeps grouping animals wrongly, calling a frog a reptile and a "
                    "bat a bird, and cannot list features shared by animals that have a backbone."),
        "item": ("An animal has moist skin, lays its eggs in water and lives both in water and on "
                 "land. Which group does it belong to? Give one feature that supports your answer."),
    },
    {
        "target": ("Grade 5", "Science and Technology", "2.1 Mixtures"),
        "teacher": ("The learner cannot choose a suitable way of getting sand out of water, and "
                    "cannot say which mixtures look uniform and which do not."),
        "item": ("You are given a jar containing iron nails, sand and salt mixed together. "
                 "Describe how you would get each one out on its own."),
    },
    {
        "target": ("Grade 5", "Science and Technology", "2.2 Water Pollution"),
        "teacher": ("The learner cannot say what makes the water in the river unsafe, and cannot "
                    "name a way of making it safe for drinking at home."),
        "item": ("Name two things that make water in a stream unsafe to drink, and describe one "
                 "method used at home to make that water safe."),
    },
    {
        "target": ("Grade 5", "Science and Technology", "3.1 Floating and Sinking"),
        "teacher": ("The learner insists that heavy things always go to the bottom, and cannot "
                    "explain why a large metal boat stays on top of the water."),
        "item": ("A stone goes to the bottom of a basin of water but a dry piece of wood of the "
                 "same size stays on top. Give one reason for the difference."),
    },
    {
        "target": ("Grade 5", "Science and Technology", "3.2 Sound Energy"),
        "teacher": ("The learner cannot explain how a drum makes a noise and does not connect "
                    "shaking or vibration with what the ear hears."),
        "item": ("A learner plucks a tight string and a noise is heard. Explain how the noise is "
                 "produced and state one effect of very loud noise on people."),
    },
    {
        "target": ("Grade 5", "Science and Technology", "3.3 Heat transfer"),
        "teacher": ("The learner cannot explain why a metal spoon left in hot porridge becomes hot "
                    "while a wooden one stays cool, and cannot say which materials are safe for "
                    "holding hot pots."),
        "item": ("A cooking pot is made of metal but its handle is covered with plastic. Explain "
                 "why the handle is made of a different material, and name a material that would "
                 "keep food warm for longer."),
    },
]


# ---------------------------------------------------------------------------
class MiniLMEmbedder:
    name = "all-MiniLM-L6-v2 (sentence-transformers)"

    def __init__(self):
        from sentence_transformers import SentenceTransformer

        print("Loading all-MiniLM-L6-v2 ...")
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def encode(self, texts, show=False):
        return np.asarray(
            self.model.encode(
                list(texts), normalize_embeddings=True, show_progress_bar=show,
                batch_size=64,
            ),
            dtype=np.float32,
        )


class TfidfEmbedder:
    """Dependency-free fallback. NOT the production embedder - bag of words with
    no semantic understanding, so treat its numbers as a floor, not a result."""

    name = "TF-IDF bag-of-words (fallback, NOT production)"

    def __init__(self, corpus):
        docs = [self._tok(t) for t in corpus]
        self.vocab = {}
        for d in docs:
            for w in set(d):
                self.vocab.setdefault(w, len(self.vocab))
        n = len(docs)
        df = np.zeros(len(self.vocab))
        for d in docs:
            for w in set(d):
                df[self.vocab[w]] += 1
        self.idf = (np.log((1 + n) / (1 + df)) + 1.0).astype(np.float32)

    @staticmethod
    def _tok(text):
        return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS]

    def encode(self, texts, show=False):
        out = np.zeros((len(texts), len(self.vocab)), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in self._tok(t):
                j = self.vocab.get(w)
                if j is not None:
                    out[i, j] += 1
        out *= self.idf
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


# ---------------------------------------------------------------------------
def rank_of(query_vec, matrix, target_idx, candidate_idx=None):
    """Return (rank of target, top-1 index, top-1 score, margin)."""
    if candidate_idx is None:
        sims = matrix @ query_vec
        order = np.argsort(sims)[::-1]
    else:
        sub = matrix[candidate_idx]
        sims_sub = sub @ query_vec
        order_sub = np.argsort(sims_sub)[::-1]
        order = np.array(candidate_idx)[order_sub]
        sims = np.full(matrix.shape[0], -1.0, dtype=np.float32)
        sims[candidate_idx] = sims_sub
    rank = int(np.where(order == target_idx)[0][0]) + 1
    top1 = int(order[0])
    margin = float(sims[order[0]] - sims[order[1]]) if len(order) > 1 else 0.0
    return rank, top1, float(sims[top1]), margin


def heading_query(chunk, words=14):
    """The chunk's own heading, trimmed. Sub-strand cells in these designs often
    carry content bullets after the title, so the query is capped rather than
    using the whole cell, which would leak the chunk body into the query."""
    text = f"{chunk['strand']} {chunk['sub_strand']}"
    return " ".join(text.split()[:words])


def find_target(chunks, grade, subject, prefix):
    pl = prefix.lower()
    for i, c in enumerate(chunks):
        if (c["grade"] == grade and c["subject"] == subject
                and c["sub_strand"].lower().startswith(pl)):
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", choices=["minilm", "tfidf"], default="minilm")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--seed", type=int, default=169962)
    args = ap.parse_args()

    path = Path(args.corpus)
    if not path.exists():
        sys.exit(f"Corpus not found at {path}. Run this from the repo root.")

    data = json.loads(path.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    rubrics = data.get("rubrics", [])
    texts = [c["text"] for c in chunks]

    print(f"corpus: {len(chunks)} curriculum chunks, {len(rubrics)} rubric rows")
    if any(not re.match(r"^\s*\d+\.\d", c.get("sub_strand", "")) for c in chunks):
        print("NOTE: some chunks have unnumbered sub-strands - rubric rows may still")
        print("      be mixed in. Run split_rubrics.py first.")

    embedder = MiniLMEmbedder() if args.embedder == "minilm" else TfidfEmbedder(texts)
    print(f"embedder: {embedder.name}")
    print("embedding corpus ...")
    matrix = embedder.encode(texts, show=True)

    results = {
        "run": datetime.now().isoformat(timespec="seconds"),
        "corpus_size": len(chunks),
        "rubric_rows": len(rubrics),
        "embedder": embedder.name,
    }

    # --- A: corpus-wide heading retrieval -----------------------------------
    rng = random.Random(args.seed)
    sample_idx = rng.sample(range(len(chunks)), min(args.sample, len(chunks)))
    queries = [heading_query(chunks[i]) for i in sample_idx]
    qm = embedder.encode(queries)

    ranks, margins, per_area = [], [], {}
    for qi, ti in enumerate(sample_idx):
        rank, _, _, margin = rank_of(qm[qi], matrix, ti)
        ranks.append(rank)
        margins.append(margin)
        area = chunks[ti]["subject"]
        per_area.setdefault(area, []).append(rank)

    ranks_arr = np.array(ranks)
    top1 = float((ranks_arr == 1).mean())
    top5 = float((ranks_arr <= 5).mean())
    mrr = float((1.0 / ranks_arr).mean())

    print("\n" + "=" * 72)
    print(f"A. CORPUS-WIDE HEADING RETRIEVAL ({len(sample_idx)} queries, "
          f"{len(chunks)} candidates)")
    print("=" * 72)
    print(f"  top-1 accuracy : {top1*100:6.1f}%")
    print(f"  top-5 accuracy : {top5*100:6.1f}%")
    print(f"  MRR            : {mrr:6.3f}")
    print(f"  mean margin    : {np.mean(margins):6.3f}")
    results["test_a"] = {"queries": len(sample_idx), "top1": top1, "top5": top5,
                         "mrr": mrr, "mean_margin": float(np.mean(margins))}

    # --- B / C: realistic phrasing, unfiltered vs pre-filtered --------------
    print("\n" + "=" * 72)
    print("B/C. REALISTIC PHRASING - WHOLE CORPUS vs GRADE+AREA PRE-FILTER")
    print("=" * 72)
    rows, missing = [], []
    for spec in DAY5_QUERIES:
        grade, subject, prefix = spec["target"]
        ti = find_target(chunks, grade, subject, prefix)
        if ti is None:
            missing.append(prefix)
            continue
        cand = [i for i, c in enumerate(chunks)
                if c["grade"] == grade and c["subject"] == subject]
        for style in ("teacher", "item"):
            qv = embedder.encode([spec[style]])[0]
            r_all, top_all, _, m_all = rank_of(qv, matrix, ti)
            r_f, top_f, _, m_f = rank_of(qv, matrix, ti, candidate_idx=cand)
            rows.append({
                "sub_strand": prefix, "style": style,
                "rank_unfiltered": r_all, "rank_filtered": r_f,
                "margin_unfiltered": m_all, "margin_filtered": m_f,
                "top1_unfiltered": chunks[top_all]["sub_strand"][:45],
                "candidates_filtered": len(cand),
            })

    if missing:
        print(f"  targets not found in corpus: {', '.join(missing)}\n")

    print(f"{'sub-strand':<30}{'style':<9}{'rank(all)':>10}{'rank(filt)':>11}  retrieved #1 (all)")
    for r in rows:
        print(f"{r['sub_strand'][:28]:<30}{r['style']:<9}{r['rank_unfiltered']:>10}"
              f"{r['rank_filtered']:>11}  {r['top1_unfiltered']}")

    if rows:
        acc_all = sum(r["rank_unfiltered"] == 1 for r in rows) / len(rows)
        acc_f = sum(r["rank_filtered"] == 1 for r in rows) / len(rows)
        print(f"\n  top-1, whole corpus       : {acc_all*100:5.1f}%  "
              f"({len(chunks)} candidates)")
        print(f"  top-1, grade+area filtered: {acc_f*100:5.1f}%  "
              f"({rows[0]['candidates_filtered']} candidates)")
        results["test_bc"] = {"rows": rows, "top1_unfiltered": acc_all,
                              "top1_filtered": acc_f}

    # --- D: per learning area ----------------------------------------------
    print("\n" + "=" * 72)
    print("D. PER LEARNING AREA (from test A)")
    print("=" * 72)
    print(f"{'learning area':<32}{'n':>5}{'top-1':>9}{'MRR':>8}")
    area_rows = []
    for area, rs in sorted(per_area.items(), key=lambda kv: -len(kv[1])):
        a = np.array(rs)
        row = {"area": area, "n": len(rs), "top1": float((a == 1).mean()),
               "mrr": float((1.0 / a).mean())}
        area_rows.append(row)
        print(f"{area[:30]:<32}{row['n']:>5}{row['top1']*100:>8.1f}%{row['mrr']:>8.3f}")
    results["test_d"] = area_rows

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = path.parent / f"retrieval_at_scale_{stamp}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nresults -> {out}")

    print("\n" + "=" * 72)
    print("PASTE THIS BACK")
    print("=" * 72)
    print(f"  corpus {len(chunks)} chunks | embedder {args.embedder}")
    print(f"  A heading   top-1 {top1*100:.1f}%  top-5 {top5*100:.1f}%  MRR {mrr:.3f}")
    if rows:
        print(f"  B realistic top-1 {acc_all*100:.1f}% unfiltered / "
              f"{acc_f*100:.1f}% grade+area filtered")
    worst = sorted(area_rows, key=lambda r: r["top1"])[:3]
    print("  D weakest areas: " + ", ".join(
        f"{r['area'][:18]} {r['top1']*100:.0f}%" for r in worst))


if __name__ == "__main__":
    main()
