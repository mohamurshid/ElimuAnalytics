/**
 * The 2-PL model in the browser, for the explainers on the landing page.
 *
 * The real estimates are made on the server (backend/app/irt.py, girth).
 * This mirrors the same model and the same rules closely enough to explain
 * them - EAP over a standard normal prior, KICD cut-offs at -1, 0 and 1, no
 * level below 5 answers, provisional below 10 - and is never used to show a
 * real learner's level.
 */

export const MIN_ANSWERS = 5;
export const CONFIDENT_ANSWERS = 10;

export type Level = {
  key: "exceeds" | "meets" | "approaches" | "below";
  label: string;
  /** Lower bound on ability (theta); the first level whose bound is met applies. */
  from: number;
};

/** KICD's four levels, highest first - the same cut-offs as the server. */
export const LEVELS: Level[] = [
  { key: "exceeds", label: "Exceeds expectation", from: 1 },
  { key: "meets", label: "Meets expectation", from: 0 },
  { key: "approaches", label: "Approaches expectation", from: -1 },
  { key: "below", label: "Below expectation", from: -Infinity },
];

export function levelFor(theta: number): Level {
  return LEVELS.find((l) => theta >= l.from) ?? LEVELS[LEVELS.length - 1];
}

/** Probability of a correct answer: the item characteristic curve. */
export function pCorrect(theta: number, a: number, b: number): number {
  return 1 / (1 + Math.exp(-a * (theta - b)));
}

export type Question = { a: number; b: number };

/** null = not attempted, which is left out - never counted as wrong. */
export type Answer = boolean | null;

const GRID = Array.from({ length: 161 }, (_, i) => -4 + i * 0.05);

/** Expected a posteriori ability over a standard normal prior. */
export function eap(questions: Question[], answers: Answer[]): number {
  let num = 0;
  let den = 0;
  for (const t of GRID) {
    let w = Math.exp((-t * t) / 2);
    questions.forEach((q, i) => {
      const x = answers[i];
      if (x === null || x === undefined) return;
      const p = pCorrect(t, q.a, q.b);
      w *= x ? p : 1 - p;
    });
    num += t * w;
    den += w;
  }
  return den > 0 ? num / den : 0;
}
