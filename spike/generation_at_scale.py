"""
Question generation, measured: checkpoint 6.

Runs the PRODUCTION prompt, schema, model call and server checks
(backend/app/questions.py and generation.py) over a stratified sample of
Grades 4-6 sub-strands, and reports what came of it. Imported, not copied,
so what is measured is what is deployed - the lesson of the Day 5 spike.

Agreed 21 October:
  * 34 sub-strands: 2 from each of the 17 grade / learning-area pairs the
    catalogue offers, chosen at random with a fixed seed
  * two settings, Haiku at low and at medium effort; one 5-question request
    per sub-strand per setting = 68 requests
  * key correctness is judged by a person, not a model: a review sheet of 40
    saved questions, 20 per setting, shuffled with the setting hidden
  * the near-copy threshold is set from human labels too: a sheet of the
    most similar question pairs, marked same / different

WHAT IT MEASURES AUTOMATICALLY
  - how many proposed questions pass the server's checks, and why the rest
    are dropped (per setting, per learning area, per language)
  - cost, tokens and time per request
  - how often the key is the longest option (chance would be about 25%)
  - where the key sits, A-D (chance 25% each)
  - question length in words, a reading-level proxy
  - for Kiswahili sub-strands, questions carrying English function words

WHAT IT DOES NOT CLAIM
  Whether the keys are right, or which pairs are paraphrases. Those come
  from the two sheets, scored with --score once a person has marked them.

USAGE (from the repository root, venv active - or `tasks gen ...`)
    python spike\\generation_at_scale.py                 plan only, no cost
    python spike\\generation_at_scale.py --go            call the API (~20 US cents)
    python spike\\generation_at_scale.py --analyse FILE  re-analyse saved raw output, free
    python spike\\generation_at_scale.py --score STAMP   score the marked sheets

Writes spike/generation_raw_<stamp>.json first (every response, so nothing
paid for is lost), then generation_at_scale_<stamp>.json and .md, and the
two sheets review_<stamp>.csv and pairs_<stamp>.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.catalogue import Row, build, lookup  # noqa: E402
from app.curriculum import get_embedder  # noqa: E402
from app.curriculum import normalise as normalise_text  # noqa: E402
from app.generation import (  # noqa: E402
    MODEL,
    QUESTIONS_PER_RUN,
    Job,
    call_model,
    check_all,
)
from app.questions import SubStrand, build_prompt, cosine, option_parts  # noqa: E402
from app.reports import price, thinking_tokens  # noqa: E402

CORPUS = ROOT / "data" / "kicd" / "kicd_curriculum_chunks_full.json"
OUT = ROOT / "spike"
EFFORTS = ("low", "medium")
PER_PAIR = 2
SEED = 169962
WORKERS = 4
# USD per request, from the three medium-effort runs of 20-21 October
# (0.28, 0.30, 0.30 cents; n=3). Used only for the estimate printed first.
COST_PER_RUN_ESTIMATE = 0.0030
REVIEW_PER_SETTING = 20
PAIRS_TOP = 25
PAIRS_BAND = 25
LETTERS = "ABCDEF"
ENGLISH_MARKERS = {"the", "is", "which", "what", "of", "and", "are", "does", "why", "how"}


# --- the sample ------------------------------------------------------------
def load_rows() -> list[Row]:
    """The corpus as ingest stores it: normalised, source_row = file index."""
    records = json.loads(CORPUS.read_text(encoding="utf-8"))["chunks"]
    return [
        Row(r["grade"], r["subject"], normalise_text(r["strand"]),
            normalise_text(r["sub_strand"]), normalise_text(r["text"]), source_row=i)
        for i, r in enumerate(records)
    ]


def sample(rows: list[Row], per_pair: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    keys: list[str] = []
    for grade in build(rows)["grades"]:
        for area in grade["learning_areas"]:
            if not area["available"]:
                continue
            pool = [s["key"] for st in area["strands"] for s in st["sub_strands"]]
            keys += rng.sample(pool, min(per_pair, len(pool)))
    return keys


def sub_strand(entry) -> SubStrand:
    return SubStrand(entry.grade, entry.learning_area, entry.strand, entry.number,
                     entry.name, entry.language)


# --- pass 1: the API -------------------------------------------------------
def one_request(entry, effort: str) -> dict:
    prompt = build_prompt(sub_strand(entry), [r.syllabus_text for r in entry.chunks],
                          QUESTIONS_PER_RUN, ())
    started = time.perf_counter()
    record = {
        "key": entry.key, "grade": entry.grade, "learning_area": entry.learning_area,
        "language": entry.language, "sub_strand": f"{entry.number} {entry.name}",
        "effort": effort, "model": MODEL, "proposed": [], "truncated": False,
        "error": None, "input_tokens": None, "output_tokens": None,
        "thinking_tokens": None, "cost_usd": None,
    }
    try:
        proposed, usage, truncated = call_model(prompt, effort)
        record.update(
            proposed=proposed, truncated=truncated,
            input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            thinking_tokens=thinking_tokens(usage), cost_usd=price(MODEL, usage),
        )
    except json.JSONDecodeError:
        record["error"] = "answer was not JSON (cost not recorded)"
    except Exception as exc:  # recorded, never fatal: the other requests are paid for
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
    record["seconds"] = round(time.perf_counter() - started, 1)
    return record


def run_api(rows: list[Row], keys: list[str]) -> Path:
    entries = {k: lookup(rows, k) for k in keys}
    jobs = [(entries[k], e) for e in EFFORTS for k in keys]
    print(f"calling the API: {len(jobs)} requests, {WORKERS} at a time")
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, record in enumerate(pool.map(lambda j: one_request(*j), jobs), start=1):
            results.append(record)
            flag = record["error"] or ("CUT OFF" if record["truncated"] else "")
            print(f"  {n:>2}/{len(jobs)} {record['effort']:<6} {record['key']:<55} "
                  f"{len(record['proposed'])} q  {record['seconds']:>5}s  {flag}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw = OUT / f"generation_raw_{stamp}.json"
    raw.write_text(json.dumps({"stamp": stamp, "seed": SEED, "per_pair": PER_PAIR,
                               "keys": keys, "runs": results}, indent=1,
                              ensure_ascii=False), encoding="utf-8")
    print(f"saved every response: {raw}")
    return raw


# --- pass 2: analysis (free, repeatable) -----------------------------------
def words(text: str) -> int:
    return len(text.split())


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a (0)"


def reason_of(problem: str) -> str:
    return re.sub(r"\s*\(similarity [0-9.]+\)", "", problem)


def analyse(raw_path: Path, rows: list[Row]) -> None:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    stamp = raw["stamp"]
    entries = {k: lookup(rows, k) for k in raw["keys"]}
    embed = get_embedder()

    kept_all: list[dict] = []
    by_effort: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for run in raw["runs"]:
        stats = by_effort[run["effort"]]
        stats["runs"].append(run)
        if run["error"] or run["truncated"]:
            continue
        entry = entries[run["key"]]
        job = Job(run_id=uuid.uuid4(), strand_id=uuid.uuid4(), requested_by=uuid.uuid4(),
                  prompt="", chunks=tuple((r.source_row, r.syllabus_text) for r in entry.chunks),
                  existing=())
        keep, dropped = check_all(run["proposed"], job, embed)
        run["kept"], run["dropped"] = keep, dropped
        for q in keep:
            kept_all.append({**q, "_run": run})
            stats["kept"].append((q, run))
        stats["dropped"] += dropped

    metrics = {}
    lines = [f"# Question generation at scale - {stamp}", "",
             f"Model {MODEL}; {len(raw['keys'])} sub-strands ({raw['per_pair']} per "
             f"grade/area pair, seed {raw['seed']}); {QUESTIONS_PER_RUN} questions asked per "
             "request. Production prompt, schema and checks. Every figure carries its n.", ""]
    for effort in EFFORTS:
        s = by_effort[effort]
        runs = s["runs"]
        ok = [r for r in runs if not r["error"] and not r["truncated"]]
        proposed = sum(len(r["proposed"]) for r in ok)
        kept = s["kept"]
        costs = [r["cost_usd"] for r in runs if r["cost_usd"] is not None]
        secs = [r["seconds"] for r in runs]
        reasons = Counter(reason_of(p) for d in s["dropped"] for p in d["problems"])
        texts = [option_parts(q) for q, _r in kept]
        longest = sum(
            1 for (opts, _m), (q, _r) in zip(texts, kept, strict=True)
            if len(opts[q["correct_option"]]) > max(
                len(o) for i, o in enumerate(opts) if i != q["correct_option"])
        )
        positions = Counter(LETTERS[q["correct_option"]] for q, _r in kept)
        qwords = [words(q["question"]) for q, _r in kept]
        sw = [(q, r) for q, r in kept if r["language"] == "Kiswahili"]
        leaks = [q["question"] for q, _r in sw
                 if len(ENGLISH_MARKERS & set(re.findall(r"[a-z]+", q["question"].lower())))
                 >= 2]
        per_area = defaultdict(lambda: [0, 0])
        for r in ok:
            per_area[r["learning_area"]][1] += len(r["proposed"])
            per_area[r["learning_area"]][0] += len(r.get("kept", []))

        metrics[effort] = {
            "requests": len(runs), "failed": len(runs) - len(ok),
            "failures": [r["error"] or "cut off" for r in runs if r not in ok],
            "proposed": proposed, "kept": len(kept), "dropped": proposed - len(kept),
            "drop_reasons": dict(reasons),
            "cost_total_usd": round(sum(costs), 5),
            "cost_mean_usd": round(statistics.mean(costs), 5) if costs else None,
            "seconds_mean": round(statistics.mean(secs), 1) if secs else None,
            "seconds_p90": round(sorted(secs)[int(0.9 * (len(secs) - 1))], 1) if secs else None,
            "key_longest": longest, "key_positions": dict(positions),
            "question_words_mean": round(statistics.mean(qwords), 1) if qwords else None,
            "question_words_max": max(qwords) if qwords else None,
            "kiswahili_kept": len(sw), "kiswahili_english_flags": leaks,
            "pass_by_area": {a: v for a, v in sorted(per_area.items())},
        }
        m = metrics[effort]
        lines += [f"## Haiku, {effort} effort", "",
                  f"- requests: {m['requests']}, failed {m['failed']} {m['failures'] or ''}",
                  f"- questions passing the checks: {pct(m['kept'], m['proposed'])}",
                  f"- drop reasons (a question can have several): {m['drop_reasons'] or 'none'}",
                  f"- cost: total ${m['cost_total_usd']}, mean ${m['cost_mean_usd']} per "
                  f"request (n={len(costs)})",
                  f"- time: mean {m['seconds_mean']} s, 90th percentile {m['seconds_p90']} s",
                  f"- key is the longest option: {pct(longest, len(kept))} (chance ~25%)",
                  f"- key position: {dict(sorted(positions.items()))} (n={len(kept)})",
                  f"- words per question: mean {m['question_words_mean']}, max "
                  f"{m['question_words_max']}",
                  f"- Kiswahili questions with English function words: "
                  f"{pct(len(leaks), len(sw))}", "",
                  "| learning area | passing the checks |", "|---|---|"]
        lines += [f"| {a} | {pct(k, p)} |" for a, (k, p) in m["pass_by_area"].items()]
        lines.append("")

    review = write_review_sheet(stamp, by_effort)
    pairs = write_pairs_sheet(stamp, raw["runs"], embed)
    lines += ["## For a person to mark", "",
              f"- {review.name}: {2 * REVIEW_PER_SETTING} saved questions, shuffled, setting "
              "hidden. Mark key_correct and misconceptions_ok.",
              f"- {pairs.name}: the most similar question pairs. Mark same_question.",
              f"- then: python spike\\generation_at_scale.py --score {stamp}", ""]

    (OUT / f"generation_at_scale_{stamp}.json").write_text(
        json.dumps({"stamp": stamp, "metrics": metrics}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    md = OUT / f"generation_at_scale_{stamp}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {md}")


def write_review_sheet(stamp: str, by_effort) -> Path:
    rng = random.Random(SEED)
    picked = []
    for effort in EFFORTS:
        kept = by_effort[effort]["kept"]
        picked += [(effort, q, r) for q, r in rng.sample(kept, min(REVIEW_PER_SETTING, len(kept)))]
    rng.shuffle(picked)
    hidden = {}
    path = OUT / f"review_{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "grade", "learning_area", "sub_strand", "question",
                    "A", "B", "C", "D", "correct", "why_right",
                    "if_A", "if_B", "if_C", "if_D", "curriculum_excerpt",
                    "key_correct (y/n)", "misconceptions_ok (y/n/partly)", "notes"])
        for n, (effort, q, run) in enumerate(picked, start=1):
            rid = f"R{n:02d}"
            hidden[rid] = effort
            opts, mis = option_parts(q)
            w.writerow([rid, run["grade"], run["learning_area"], run["sub_strand"],
                        q["question"], *opts[:4], LETTERS[q["correct_option"]],
                        q["rationale"], *mis[:4], q["excerpt"], "", "", ""])
    (OUT / f"review_{stamp}_key.json").write_text(json.dumps(hidden, indent=1),
                                                  encoding="utf-8")
    return path


def write_pairs_sheet(stamp: str, runs: list[dict], embed) -> Path:
    """Pairs of questions about the same sub-strand, across both settings:
    the closest, plus a spread from the band where a threshold might sit."""
    by_key = defaultdict(list)
    for r in runs:
        by_key[r["key"]] += [q.get("question", "").strip() for q in r["proposed"]
                             if q.get("question")]
    pairs = []
    for key, qs in by_key.items():
        qs = list(dict.fromkeys(qs))
        vecs = embed(qs) if qs else []
        for i in range(len(qs)):
            for j in range(i + 1, len(qs)):
                pairs.append((round(cosine(vecs[i], vecs[j]), 3), key, qs[i], qs[j]))
    pairs.sort(reverse=True)
    top = pairs[:PAIRS_TOP]
    floor = top[-1][0] if top else 1.0
    band = [p for p in pairs[PAIRS_TOP:] if 0.70 <= p[0] < floor]
    rng = random.Random(SEED)
    chosen = sorted(top + rng.sample(band, min(PAIRS_BAND, len(band))), reverse=True)
    path = OUT / f"pairs_{stamp}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "similarity", "sub_strand", "question_1", "question_2",
                    "same_question (y/n)"])
        for n, (sim, key, a, b) in enumerate(chosen, start=1):
            w.writerow([f"P{n:02d}", sim, key, a, b, ""])
    return path


# --- pass 3: the people's marks ---------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> str:
    if not n:
        return "n/a"
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{100 * p:.0f}% ({k}/{n}; 95% CI {100 * (centre - half):.0f}-{100 * (centre + half):.0f}%)"


def yes(value: str) -> bool | None:
    v = (value or "").strip().lower()
    return True if v.startswith("y") else False if v.startswith("n") else None


def score(stamp: str) -> None:
    hidden = json.loads((OUT / f"review_{stamp}_key.json").read_text(encoding="utf-8"))
    with (OUT / f"review_{stamp}.csv").open(encoding="utf-8-sig") as f:
        marks = list(csv.DictReader(f))
    lines = [f"# Hand-checked results - {stamp}", ""]
    for label, rows_ in [("all", marks)] + [
        (e, [m for m in marks if hidden[m["review_id"]] == e]) for e in EFFORTS
    ]:
        keys = [yes(m["key_correct (y/n)"]) for m in rows_]
        judged = [k for k in keys if k is not None]
        mis = [(m["misconceptions_ok (y/n/partly)"] or "").strip().lower() for m in rows_]
        lines.append(f"- {label}: key correct {wilson(sum(judged), len(judged))}; "
                     f"misconceptions ok {sum(x.startswith('y') for x in mis)}, partly "
                     f"{sum(x.startswith('p') for x in mis)}, no "
                     f"{sum(x.startswith('n') for x in mis)}")
    with (OUT / f"pairs_{stamp}.csv").open(encoding="utf-8-sig") as f:
        pairs = [(float(p["similarity"]), yes(p["same_question (y/n)"])) for p in csv.DictReader(f)]
    pairs = [(s, same) for s, same in pairs if same is not None]
    lines += ["", f"## Near-copy threshold (n={len(pairs)} labelled pairs)", "",
              "| threshold | flagged | of which same (precision) | same caught (recall) |",
              "|---|---|---|---|"]
    total_same = sum(1 for _s, same in pairs if same)
    for t in (0.75, 0.80, 0.85, 0.90, 0.95):
        flagged = [same for s, same in pairs if s >= t]
        hit = sum(flagged)
        lines.append(f"| {t:.2f} | {len(flagged)} | {pct(hit, len(flagged))} | "
                     f"{pct(hit, total_same)} |")
    out = OUT / f"generation_scored_{stamp}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--go", action="store_true", help="call the API (costs money)")
    ap.add_argument("--analyse", metavar="RAW_JSON", help="re-analyse saved output, free")
    ap.add_argument("--score", metavar="STAMP", help="score the marked sheets")
    ap.add_argument("--per-pair", type=int, default=PER_PAIR)
    args = ap.parse_args()

    if args.score:
        score(args.score)
        return
    rows = load_rows()
    if args.analyse:
        analyse(Path(args.analyse), rows)
        return

    keys = sample(rows, args.per_pair, SEED)
    requests = len(keys) * len(EFFORTS)
    print(f"sample: {len(keys)} sub-strands ({args.per_pair} per grade/area pair, seed {SEED})")
    for k in keys:
        print(f"  {k}")
    print(f"settings: Haiku ({MODEL}) at {', '.join(EFFORTS)} effort -> {requests} requests")
    print(f"estimated cost: about ${requests * COST_PER_RUN_ESTIMATE:.2f} "
          f"(from 3 medium-effort runs; low effort should cost less)")
    if not args.go:
        print("plan only - nothing was sent. Add --go to call the API.")
        return
    raw = run_api(rows, keys)
    analyse(raw, rows)


if __name__ == "__main__":
    main()
