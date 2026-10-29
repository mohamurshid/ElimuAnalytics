"use client";

/**
 * "Percentages can mislead": two learners, two quizzes of different
 * difficulty. Tap an answer to change it - right, wrong, or not attempted -
 * and watch the percentage and the IRT estimate part company.
 *
 * Starts where the point is plain: Amina has the higher percentage on the
 * easier questions, Baraka the lower one on the harder questions, and IRT
 * places Baraka higher. Not attempted is left out rather than marked wrong,
 * and below five answers there is no level at all - the server's rules.
 */

import { useState } from "react";

import { type Answer, CONFIDENT_ANSWERS, MIN_ANSWERS, type Question, eap, levelFor } from "@/lib/irt";

import { TIER_BG } from "./tiers";

type Learner = {
  name: string;
  quiz: string;
  questions: (Question & { label: string })[];
  start: Answer[];
};

const EASY = [-2, -1.6, -1.2, -0.9, -0.6, -0.3];
const HARD = [0.3, 0.6, 0.9, 1.2, 1.5, 1.8];
const tag = (b: number) => (b < -1 ? "easy" : b < 0.5 ? "medium" : b < 1.3 ? "hard" : "very hard");

const LEARNERS: Learner[] = [
  {
    name: "Amina",
    quiz: "Easier questions",
    questions: EASY.map((b) => ({ a: 1.3, b, label: tag(b) })),
    start: [true, true, true, true, false, false],
  },
  {
    name: "Baraka",
    quiz: "Harder questions",
    questions: HARD.map((b) => ({ a: 1.3, b, label: tag(b) })),
    start: [true, true, true, false, false, false],
  },
];

function next(a: Answer): Answer {
  return a === true ? false : a === false ? null : true;
}

export function SameScore() {
  const [answers, setAnswers] = useState<Answer[][]>(LEARNERS.map((l) => l.start));

  const results = LEARNERS.map((l, i) => {
    const given = answers[i].filter((x) => x !== null);
    const right = given.filter(Boolean).length;
    const enough = given.length >= MIN_ANSWERS;
    const theta = eap(l.questions, answers[i]);
    return {
      answered: given.length,
      right,
      pct: given.length ? Math.round((100 * right) / given.length) : null,
      theta: enough ? theta : null,
      level: enough ? levelFor(theta) : null,
    };
  });

  const [r0, r1] = results;
  let verdict: string | null = null;
  if (r0.theta !== null && r1.theta !== null && r0.pct !== null && r1.pct !== null) {
    const pctSays = r0.pct === r1.pct ? 0 : r0.pct > r1.pct ? 1 : -1;
    const irtSays = Math.abs(r0.theta - r1.theta) < 0.05 ? 0 : r0.theta > r1.theta ? 1 : -1;
    if (pctSays !== 0 && irtSays !== 0 && pctSays !== irtSays) {
      const [hiPct, hiIrt] = pctSays > 0 ? ["Amina", "Baraka"] : ["Baraka", "Amina"];
      verdict = `${hiPct} has the higher percentage, but ${hiIrt} shows more ability: ${hiIrt}'s questions were harder. A percentage cannot see that; IRT can.`;
    } else if (pctSays === 0 && irtSays !== 0) {
      verdict = `Same percentage, different ability: ${irtSays > 0 ? "Amina" : "Baraka"}'s correct answers were on harder questions.`;
    } else {
      verdict = "Here the percentage and IRT agree. Try giving Amina more right answers on her easier quiz.";
    }
  }

  return (
    <div>
      <div className="grid gap-4 md:grid-cols-2">
        {LEARNERS.map((l, i) => (
          <LearnerCard
            key={l.name}
            learner={l}
            answers={answers[i]}
            result={results[i]}
            onTap={(q) =>
              setAnswers((all) =>
                all.map((row, r) => (r === i ? row.map((x, c) => (c === q ? next(x) : x)) : row)),
              )
            }
          />
        ))}
      </div>
      <p aria-live="polite" className="mt-5 rounded-xl border border-line bg-sunken px-4 py-3 text-[15px] leading-relaxed text-ink">
        {verdict ?? "Each learner needs at least five answers before IRT gives a level — a guess from fewer would be noise."}
      </p>
      <button
        type="button"
        onClick={() => setAnswers(LEARNERS.map((l) => l.start))}
        className="mt-3 text-sm font-medium text-ink-muted underline-offset-4 hover:text-ink hover:underline"
      >
        Reset the example
      </button>
    </div>
  );
}

function LearnerCard({
  learner,
  answers,
  result,
  onTap,
}: {
  learner: Learner;
  answers: Answer[];
  result: { answered: number; right: number; pct: number | null; theta: number | null; level: ReturnType<typeof levelFor> | null };
  onTap: (question: number) => void;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-lg font-semibold text-ink">{learner.name}</p>
        <p className="text-sm text-ink-muted">{learner.quiz}</p>
      </div>

      <ol className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {learner.questions.map((q, i) => {
          const a = answers[i];
          const state = a === true ? "right" : a === false ? "wrong" : "not attempted";
          return (
            <li key={i}>
              <button
                type="button"
                onClick={() => onTap(i)}
                aria-label={`${learner.name}, question ${i + 1}, ${q.label}: ${state}. Tap to change.`}
                className={`flex h-16 w-full flex-col items-center justify-center rounded-xl border text-sm transition-all active:scale-95 ${
                  a === true
                    ? "border-action bg-action text-action-ink"
                    : a === false
                      ? "border-line-strong bg-surface text-ink"
                      : "border-dashed border-line-strong bg-transparent text-ink-subtle"
                }`}
              >
                <span className="text-lg leading-none">{a === true ? "✓" : a === false ? "✗" : "–"}</span>
                <span className="mt-1 text-[11px] opacity-80">{q.label}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <dl className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-sunken p-3">
          <dt className="text-xs font-medium text-ink-muted">Percentage</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums text-ink">
            {result.pct === null ? "–" : `${result.pct}%`}
          </dd>
          <dd className="text-xs text-ink-subtle">
            {result.right} of {result.answered} answered
          </dd>
        </div>
        <div className="rounded-xl bg-sunken p-3">
          <dt className="text-xs font-medium text-ink-muted">IRT ability</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums text-ink">
            {result.theta === null ? "–" : result.theta.toFixed(2).replace("-", "−")}
          </dd>
          <dd className="text-xs text-ink-subtle">
            {result.theta === null ? `needs ${MIN_ANSWERS}+ answers` : `provisional below ${CONFIDENT_ANSWERS}`}
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex min-h-9 items-center gap-2 text-[15px]">
        {result.level ? (
          <>
            <span className={`size-4 rounded ${TIER_BG[result.level.key]} transition-colors duration-500`} />
            <span className="font-medium text-ink">{result.level.label}</span>
          </>
        ) : (
          <span className="text-ink-muted">No level yet — not enough evidence</span>
        )}
      </div>
    </div>
  );
}
