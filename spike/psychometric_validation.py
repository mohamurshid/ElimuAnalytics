"""
Psychometric validation of the 2-PL ability model (Chapter 3, Section 3.2.4; NFR-02).

The methodology set two acceptance criteria that had not been measured:

  * model fit, RMSEA below 0.06;
  * criterion validity, F1-score of 0.75 or above on a held-out 20% of learners;

and, alongside them, item fit (infit and outfit mean squares between 0.7 and 1.3).

This script measures all three on the Riiid sample, using the production
calibration and ability code (backend/app/irt.py), so the figures describe the
code that ships rather than a copy of it.

Model fit
    RMSEA here is RMSEA2, computed from the limited-information statistic M2
    (Maydeu-Olivares & Joe, 2005; 2006; RMSEA2 as in Maydeu-Olivares & Joe,
    2014). M2 compares the observed proportions of each question answered
    correctly, and of each pair of questions both answered correctly, with the
    proportions the fitted model implies. It needs learners who answered the
    same questions, and the Riiid sample is sparse, so it is computed on the
    densest block in the data: the questions most learners answered (Riiid's
    onboarding diagnostic), using only the learners who answered all of them.
    --selfcheck simulates data from the fitted model itself and recomputes M2;
    if the statistic is implemented correctly its mean is close to its degrees
    of freedom and RMSEA2 is close to 0.

Item fit
    Infit and outfit mean squares for every calibrated question, from the
    residuals of the calibration learners' answers at their EAP abilities.

Criterion validity
    Learners are split 80/20 at random. Questions are calibrated on the 80%
    only, in batches of at most 300 (the production limit), most-answered
    questions first. For each held-out learner with at least ten answers in a
    batch, ability is estimated from the first half of their answers in time
    order, and each later answer is predicted correct when the model gives it a
    probability of at least 0.5. Precision, recall and F1 are reported for
    "correct" (as the methodology specified) and for "incorrect" (the answers
    that point to a gap), with AUC, and against three baselines that use no
    ability estimate: always correct, the question's difficulty alone, and the
    learner's own earlier proportion correct.

Usage (from the repository root):
    python spike/psychometric_validation.py --data path/to/riiid_sample_by_users.csv
    python spike/psychometric_validation.py --data ... --batches 3 --selfcheck 50
    tasks psy        (Windows; reads data\\riiid_sample_by_users.csv)

Results are printed and saved as spike/psychometric_validation_<timestamp>.json
and .md, each figure with its sample size.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.stats import chi2, rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.irt import (  # noqa: E402  (production code, imported on purpose)
    MAX_ITEMS_PER_CALIBRATION,
    MIN_RESPONSES,
    calibrate,
    estimate_abilities,
)
from girth import INVALID_RESPONSE, twopl_mml  # noqa: E402

SEED = 169962
MIN_RESPONSES_PER_ITEM = 30  # Section 3.2.2
FIT_LOW, FIT_HIGH = 0.7, 1.3  # Section 3.2.4
RMSEA_TARGET = 0.06  # Section 3.2.4 / NFR-02
F1_TARGET = 0.75  # Section 3.2.4 / NFR-02
QUAD_N = 61


# --------------------------------------------------------------------------- data
class Responses:
    """First attempts at questions, as parallel arrays sorted by learner, then time.

    Plain NumPy rather than pandas, so the script runs in the backend's own
    virtual environment without a new dependency.
    """

    def __init__(self, ts, user, item, correct):
        self.ts, self.user, self.item, self.correct = ts, user, item, correct

    def where(self, mask) -> Responses:
        return Responses(self.ts[mask], self.user[mask], self.item[mask], self.correct[mask])

    def __len__(self) -> int:
        return len(self.user)


def load_responses(path: Path) -> Responses:
    """Question rows only (lectures dropped), first attempt of each learner at each question."""
    ts, user, item, correct = [], [], [], []
    with open(path, newline="") as f:
        rows = csv.reader(f)
        head = next(rows)
        c_ts, c_user, c_item, c_type, c_ok = (
            head.index(k) for k in ("timestamp", "user_id", "content_id", "content_type_id", "answered_correctly")
        )
        for row in rows:
            if row[c_type] != "0":
                continue
            ts.append(int(row[c_ts]))
            user.append(int(row[c_user]))
            item.append(int(row[c_item]))
            correct.append(int(row[c_ok]))
    ts, user, item, correct = (np.asarray(v, dtype=np.int64) for v in (ts, user, item, correct))
    order = np.lexsort((ts, user))
    ts, user, item, correct = ts[order], user[order], item[order], correct[order]
    _, first = np.unique(user * 100_000 + item, return_index=True)  # earliest attempt wins
    keep = np.sort(first)
    return Responses(ts[keep], user[keep], item[keep], correct[keep])


def positions(values: np.ndarray, wanted) -> np.ndarray:
    """Index of each value within `wanted` (every value must be present)."""
    wanted = np.asarray(wanted)
    order = np.argsort(wanted)
    return order[np.searchsorted(wanted[order], values)]


def matrix_for(r: Responses, items, users) -> np.ndarray:
    """ITEMS x LEARNERS, integer 0/1, INVALID_RESPONSE where unanswered (Day 1 rules)."""
    mask = np.isin(r.item, items) & np.isin(r.user, users)
    matrix = np.full((len(items), len(users)), INVALID_RESPONSE, dtype=int)
    matrix[positions(r.item[mask], items), positions(r.user[mask], users)] = r.correct[mask]
    return matrix


def most_answered(r: Responses) -> tuple[np.ndarray, np.ndarray]:
    """Questions and their answer counts, most answered first (ties by question id)."""
    items, counts = np.unique(r.item, return_counts=True)
    order = np.lexsort((items, -counts))
    return items[order], counts[order]


# ------------------------------------------------------------------- 2-PL helpers
def p_correct(theta, a, b):
    """2-PL probability, girth's parameterisation: 1 / (1 + exp(-a (theta - b)))."""
    return 1.0 / (1.0 + np.exp(-np.outer(theta, a) + a * b))


def quadrature(n=QUAD_N):
    nodes, weights = np.polynomial.hermite_e.hermegauss(n)
    return nodes, weights / weights.sum()


# -------------------------------------------------------------------- model fit
def m2_rmsea(data: np.ndarray, a: np.ndarray, b: np.ndarray) -> dict:
    """M2 and RMSEA2 for a 2-PL fitted to complete binary data (learners x items)."""
    n_obs, n = data.shape
    nodes, w = quadrature()
    P = p_correct(nodes, a, b)  # nodes x items
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    sets = [(i,) for i in range(n)] + pairs
    s, q = len(sets), 2 * n
    df_ = s - q

    observed = np.array([data[:, list(u)].all(axis=1).mean() for u in sets])
    M = np.stack([np.prod(P[:, list(u)], axis=1) for u in sets], axis=1)  # nodes x s
    implied = w @ M

    # Xi: asymptotic covariance of the first- and second-order margins,
    # Cov(m_u, m_v) = pi(u union v) - pi(u) pi(v); x_k^2 = x_k for binary items.
    E = (M * w[:, None]).T @ M
    for r, u in enumerate(sets):
        for c in range(r, s):
            v = sets[c]
            if set(u) & set(v):
                union = sorted(set(u) | set(v))
                E[r, c] = E[c, r] = w @ np.prod(P[:, union], axis=1)
    xi = E - np.outer(implied, implied)

    # Delta: derivatives of the implied margins with respect to (a, b).
    dPa = P * (1 - P) * (nodes[:, None] - b)
    dPb = -P * (1 - P) * a
    delta = np.zeros((s, q))
    for r, u in enumerate(sets):
        for k in u:
            rest = [m for m in u if m != k]
            others = np.prod(P[:, rest], axis=1) if rest else 1.0
            delta[r, k] = w @ (dPa[:, k] * others)
            delta[r, n + k] = w @ (dPb[:, k] * others)

    xi_inv_delta = np.linalg.solve(xi, delta)
    xi_inv_e = np.linalg.solve(xi, observed - implied)
    middle = np.linalg.solve(delta.T @ xi_inv_delta, delta.T @ xi_inv_e)
    m2 = float(n_obs * ((observed - implied) @ xi_inv_e - (delta.T @ xi_inv_e) @ middle))
    rmsea = float(np.sqrt(max(m2 - df_, 0.0) / (n_obs * df_)))
    return {
        "M2": m2,
        "df": int(df_),
        "p_value": float(chi2.sf(m2, df_)),
        "RMSEA2": rmsea,
        "n_learners": int(n_obs),
        "n_items": int(n),
    }


def dense_block(r: Responses, min_learners: int, candidates: int = 120):
    """Most-answered questions, added while enough learners answered all of them."""
    items, _ = most_answered(r)
    by_item = {int(i): set(r.user[r.item == i].tolist()) for i in items[:candidates]}
    block, common = [], None
    for item in (int(i) for i in items[:candidates]):
        both = by_item[item] if common is None else common & by_item[item]
        if len(both) >= min_learners:
            block.append(item)
            common = both
    return block, sorted(common)


def model_fit(r: Responses, min_learners: int, selfcheck: int) -> dict:
    items, users = dense_block(r, min_learners)
    responses = matrix_for(r, items, users)  # items x learners, complete
    params = calibrate(responses, len(items), len(users))  # production code
    a, b = params["discrimination"], params["difficulty"]
    result = m2_rmsea(responses.T, a, b)
    result["discrimination_below_0.3"] = int((a < 0.3).sum())

    if selfcheck:
        rng = np.random.default_rng(SEED)
        sims = []
        for _ in range(selfcheck):
            theta = rng.standard_normal(len(users))
            sim = (rng.random((len(users), len(items))) < p_correct(theta, a, b)).astype(int)
            fit = twopl_mml(sim.T)
            sims.append(m2_rmsea(sim, np.asarray(fit["Discrimination"]), np.asarray(fit["Difficulty"])))
        m2s = np.array([r["M2"] for r in sims])
        result["selfcheck"] = {
            "replications": selfcheck,
            "mean_M2": float(m2s.mean()),
            "df": result["df"],
            "mean_RMSEA2": float(np.mean([r["RMSEA2"] for r in sims])),
            "share_p_below_0.05": float(np.mean([r["p_value"] < 0.05 for r in sims])),
        }
    return result


# --------------------------------------------------------------------- item fit
def item_fit(responses: np.ndarray, a, b, theta) -> dict:
    """Infit and outfit mean squares per item from answered cells only."""
    answered = responses != INVALID_RESPONSE
    P = p_correct(theta, a, b).T  # items x learners
    x = np.where(answered, responses, 0)
    var = P * (1 - P)
    sq = np.where(answered, (x - P) ** 2, 0.0)
    n_ans = answered.sum(axis=1)
    outfit = np.where(answered, sq / var, 0.0).sum(axis=1) / n_ans
    infit = sq.sum(axis=1) / np.where(answered, var, 0.0).sum(axis=1)
    return {"infit": infit, "outfit": outfit}


# -------------------------------------------------------------- criterion validity
def scores(y, pred) -> dict:
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())

    def f(p_, r_):
        return 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0

    prec_c = tp / (tp + fp) if tp + fp else 0.0
    rec_c = tp / (tp + fn) if tp + fn else 0.0
    prec_w = tn / (tn + fn) if tn + fn else 0.0
    rec_w = tn / (tn + fp) if tn + fp else 0.0
    return {
        "accuracy": (tp + tn) / len(y),
        "precision_correct": prec_c,
        "recall_correct": rec_c,
        "F1_correct": f(prec_c, rec_c),
        "precision_incorrect": prec_w,
        "recall_incorrect": rec_w,
        "F1_incorrect": f(prec_w, rec_w),
        "macro_F1": (f(prec_c, rec_c) + f(prec_w, rec_w)) / 2,
    }


def auc(y, score) -> float:
    """Probability that a correct answer is given a higher score than a wrong one."""
    ranks = rankdata(score)
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def criterion_validity(r: Responses, n_batches: int) -> dict:
    rng = np.random.default_rng(SEED)
    users = np.unique(r.user)
    test_users = np.sort(rng.choice(users, size=round(0.2 * len(users)), replace=False))
    held_out = np.isin(r.user, test_users)
    train, test = r.where(~held_out), r.where(held_out)
    train_users = np.setdiff1d(users, test_users)

    items, counts = most_answered(train)
    items = items[counts >= MIN_RESPONSES_PER_ITEM]
    step = MAX_ITEMS_PER_CALIBRATION
    batches = [items[i:i + step].tolist() for i in range(0, len(items), step)]

    y_all, p_all, item_all, learner_all, keep_all = [], [], [], [], []
    learner_theta, learner_later = [], []
    fit_all, per_batch = [], []
    for k, items in enumerate(batches[:n_batches]):
        t0 = time.time()
        bt_users = np.unique(train.user[np.isin(train.item, items)])
        responses = matrix_for(train, items, bt_users)
        params = calibrate(responses, len(items), len(bt_users))  # production code
        a, b = params["discrimination"], params["difficulty"]
        theta_train = estimate_abilities(responses, params)  # production code
        fit = item_fit(responses, a, b, theta_train)
        fit_all.append(np.c_[fit["infit"], fit["outfit"], a])

        tb = test.where(np.isin(test.item, items))  # still sorted by learner, then time
        starts = np.r_[0, np.flatnonzero(np.diff(tb.user)) + 1, len(tb)]
        n_learners = 0
        for lo, hi in zip(starts[:-1], starts[1:]):
            if hi - lo < 2 * MIN_RESPONSES:
                continue
            half = lo + (hi - lo) // 2
            seen_rows = positions(tb.item[lo:half], items)
            rows = positions(tb.item[half:hi], items)
            seen_ok, later_ok = tb.correct[lo:half], tb.correct[half:hi]
            column = np.full((len(items), 1), INVALID_RESPONSE, dtype=int)
            column[seen_rows, 0] = seen_ok
            theta = estimate_abilities(column, params)[0]  # production code
            learner_theta.append(theta)
            learner_later.append(later_ok.mean())
            keep_all.append(a[rows] >= 0.3)
            y_all.append(later_ok)
            p_all.append(1.0 / (1.0 + np.exp(-a[rows] * (theta - b[rows]))))
            item_all.append(1.0 / (1.0 + np.exp(a[rows] * b[rows])))  # theta = 0: difficulty alone
            learner_all.append(np.full(len(rows), seen_ok.mean()))
            n_learners += 1
        per_batch.append({
            "batch": k + 1,
            "items": len(items),
            "calibration_learners": len(bt_users),
            "held_out_learners_scored": n_learners,
            "seconds": round(time.time() - t0, 1),
        })
        print(f"  batch {k + 1}: {len(items)} items, {len(bt_users)} calibration learners, "
              f"{n_learners} held-out learners scored ({per_batch[-1]['seconds']} s)", flush=True)

    y = np.concatenate(y_all)
    p = np.concatenate(p_all)
    item_p = np.concatenate(item_all)
    learner_p = np.concatenate(learner_all)
    keep = np.concatenate(keep_all)
    fits = np.vstack(fit_all)
    infit, outfit, disc = fits[:, 0], fits[:, 1], fits[:, 2]
    inside = (infit >= FIT_LOW) & (infit <= FIT_HIGH) & (outfit >= FIT_LOW) & (outfit <= FIT_HIGH)
    return {
        "learners": {"total": int(len(users)), "calibration": int(len(train_users)), "held_out": int(len(test_users))},
        "batches": per_batch,
        "predictions": int(len(y)),
        "share_correct": float(y.mean()),
        "model": {**scores(y, (p >= 0.5).astype(int)), "AUC": auc(y, p)},
        "baseline_always_correct": scores(y, np.ones_like(y)),
        "baseline_difficulty_only": {**scores(y, (item_p >= 0.5).astype(int)), "AUC": auc(y, item_p)},
        "baseline_learner_only": {**scores(y, (learner_p >= 0.5).astype(int)), "AUC": auc(y, learner_p)},
        # Section 3.2.3 excludes questions with discrimination below 0.3 from the
        # active bank; production does not yet, so this is reported as a variant.
        "model_without_low_discrimination": {
            **scores(y[keep], (p[keep] >= 0.5).astype(int)),
            "AUC": auc(y[keep], p[keep]),
            "predictions": int(keep.sum()),
            "baseline_always_correct_F1_correct": scores(y[keep], np.ones(int(keep.sum()), dtype=int))["F1_correct"],
        },
        # Does a learner's ability, estimated from their earlier answers, rank
        # them by how they do on their later ones? One row per learner and batch.
        "learner_level": {
            "pairs": len(learner_theta),
            "pearson_theta_vs_later_proportion": float(np.corrcoef(learner_theta, learner_later)[0, 1]),
            "spearman_theta_vs_later_proportion": float(np.corrcoef(rankdata(learner_theta), rankdata(learner_later))[0, 1]),
        },
        "item_fit": {
            "items": int(len(infit)),
            "infit_median": float(np.median(infit)),
            "outfit_median": float(np.median(outfit)),
            "share_infit_and_outfit_in_range": float(inside.mean()),
            "share_infit_in_range": float(((infit >= FIT_LOW) & (infit <= FIT_HIGH)).mean()),
            "share_outfit_in_range": float(((outfit >= FIT_LOW) & (outfit <= FIT_HIGH)).mean()),
            "discrimination_below_0.3": int((disc < 0.3).sum()),
        },
    }


# ----------------------------------------------------------------------- report
def markdown(r: dict) -> str:
    fit, cv = r["model_fit"], r["criterion_validity"]
    m, b1, b2, b3 = cv["model"], cv["baseline_always_correct"], cv["baseline_difficulty_only"], cv["baseline_learner_only"]
    pct = lambda v: f"{100 * v:.1f}%"  # noqa: E731
    lines = [
        f"# Psychometric validation, {r['run']}",
        "",
        f"Data: {r['data']} ({r['rows']:,} first attempts, {r['learners']:,} learners, {r['questions']:,} questions). Seed {SEED}.",
        "",
        "## Model fit (target RMSEA below 0.06)",
        "",
        f"Dense block: {fit['n_items']} questions answered by all of {fit['n_learners']:,} learners.",
        "",
        "| Statistic | Value |",
        "|---|---|",
        f"| M2 | {fit['M2']:.1f} on {fit['df']} df (p = {fit['p_value']:.3g}) |",
        f"| RMSEA2 | **{fit['RMSEA2']:.4f}** ({'meets' if fit['RMSEA2'] < RMSEA_TARGET else 'does not meet'} the 0.06 target) |",
        f"| Questions with discrimination below 0.3 | {fit['discrimination_below_0.3']} of {fit['n_items']} |",
    ]
    if "selfcheck" in fit:
        s = fit["selfcheck"]
        lines += [
            "",
            f"Self-check, {s['replications']} data sets simulated from the fitted model: mean M2 {s['mean_M2']:.1f} "
            f"against {s['df']} df, mean RMSEA2 {s['mean_RMSEA2']:.4f}, p below 0.05 in {pct(s['share_p_below_0.05'])} "
            "(about 5% expected if M2 is implemented correctly).",
        ]
    itf = cv["item_fit"]
    lines += [
        "",
        f"## Item fit (target infit and outfit {FIT_LOW} to {FIT_HIGH})",
        "",
        f"{itf['items']} calibrated questions: infit median {itf['infit_median']:.2f}, outfit median {itf['outfit_median']:.2f}; "
        f"both in range for {pct(itf['share_infit_and_outfit_in_range'])} (infit {pct(itf['share_infit_in_range'])}, "
        f"outfit {pct(itf['share_outfit_in_range'])}); {itf['discrimination_below_0.3']} with discrimination below 0.3.",
        "",
        "## Criterion validity (target F1 0.75 or above)",
        "",
        f"Learners: {cv['learners']['calibration']:,} for calibration, {cv['learners']['held_out']:,} held out. "
        f"Predictions: {cv['predictions']:,} later answers of held-out learners ({pct(cv['share_correct'])} correct).",
        "",
        "| | F1, correct | F1, incorrect | Macro F1 | Accuracy | AUC |",
        "|---|---|---|---|---|---|",
        f"| **2-PL ability model** | **{m['F1_correct']:.3f}** | {m['F1_incorrect']:.3f} | {m['macro_F1']:.3f} | {pct(m['accuracy'])} | {m['AUC']:.3f} |",
        f"| Always correct | {b1['F1_correct']:.3f} | {b1['F1_incorrect']:.3f} | {b1['macro_F1']:.3f} | {pct(b1['accuracy'])} | 0.500 |",
        f"| Difficulty only | {b2['F1_correct']:.3f} | {b2['F1_incorrect']:.3f} | {b2['macro_F1']:.3f} | {pct(b2['accuracy'])} | {b2['AUC']:.3f} |",
        f"| Learner's earlier proportion only | {b3['F1_correct']:.3f} | {b3['F1_incorrect']:.3f} | {b3['macro_F1']:.3f} | {pct(b3['accuracy'])} | {b3['AUC']:.3f} |",
        "",
        f"Without the questions whose discrimination is below 0.3 (Section 3.2.3 excludes them; production does not yet), "
        f"{cv['model_without_low_discrimination']['predictions']:,} predictions: F1 correct "
        f"{cv['model_without_low_discrimination']['F1_correct']:.3f} (always correct "
        f"{cv['model_without_low_discrimination']['baseline_always_correct_F1_correct']:.3f}), F1 incorrect "
        f"{cv['model_without_low_discrimination']['F1_incorrect']:.3f}, AUC {cv['model_without_low_discrimination']['AUC']:.3f}.",
        "",
        f"Learner level ({cv['learner_level']['pairs']} learner-batch pairs): ability from earlier answers against proportion "
        f"correct on later answers, Pearson {cv['learner_level']['pearson_theta_vs_later_proportion']:.3f}, "
        f"Spearman {cv['learner_level']['spearman_theta_vs_later_proportion']:.3f}.",
        "",
        f"Model precision / recall, correct: {m['precision_correct']:.3f} / {m['recall_correct']:.3f}; "
        f"incorrect: {m['precision_incorrect']:.3f} / {m['recall_incorrect']:.3f}.",
        "",
        "Batches: " + "; ".join(
            f"{x['batch']}: {x['items']} questions, {x['calibration_learners']:,} calibration learners, "
            f"{x['held_out_learners_scored']} held-out learners scored" for x in cv["batches"]) + ".",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path, help="riiid_sample_by_users.csv")
    ap.add_argument("--batches", type=int, default=3, help="calibration batches of 300 questions to score (default 3)")
    ap.add_argument("--min-learners", type=int, default=1000, help="learners who must have answered every question in the dense block")
    ap.add_argument("--selfcheck", type=int, default=50, help="simulated replications to check M2 (default 50; 0 to skip)")
    args = ap.parse_args()

    run = datetime.now().strftime("%Y%m%d_%H%M%S")
    q = load_responses(args.data)
    n_learners, n_questions = len(np.unique(q.user)), len(np.unique(q.item))
    print(f"{len(q):,} first attempts, {n_learners:,} learners, {n_questions:,} questions")

    print("Model fit (M2 / RMSEA2) on the dense block...", flush=True)
    t0 = time.time()
    fit = model_fit(q, args.min_learners, args.selfcheck)
    print(f"  done in {time.time() - t0:.0f} s")

    print("Criterion validity and item fit...", flush=True)
    cv = criterion_validity(q, args.batches)

    result = {
        "run": run,
        "data": args.data.name,
        "rows": int(len(q)),
        "learners": int(n_learners),
        "questions": int(n_questions),
        "seed": SEED,
        "model_fit": fit,
        "criterion_validity": cv,
    }
    out = ROOT / "spike" / f"psychometric_validation_{run}"
    out.with_suffix(".json").write_text(json.dumps(result, indent=2))
    report = markdown(result)
    out.with_suffix(".md").write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"Saved {out.with_suffix('.json').name} and {out.with_suffix('.md').name}")


if __name__ == "__main__":
    main()
