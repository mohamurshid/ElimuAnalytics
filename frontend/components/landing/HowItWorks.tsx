"use client";

/**
 * The core workflow, one step at a time: a list of steps on the left and
 * the chosen step opened on the right (stacked on a phone). Each step says
 * what the teacher does and what the system does for them.
 */

import { useState } from "react";

import { TIER_BG } from "./tiers";

type Step = {
  title: string;
  teacher: string;
  system: string;
  visual: React.ReactNode;
};

const STEPS: Step[] = [
  {
    title: "Choose what to assess",
    teacher: "Pick the sub-strands your class is working on.",
    system: "Lists all 427 sub-strands of the KICD Grade 4–6 curriculum designs, in curriculum order.",
    visual: (
      <ul className="space-y-1.5 text-sm">
        {["3.1 Light", "3.2 Heat transfer", "2.1 Mixtures"].map((s, i) => (
          <li key={s} className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2">
            <span className={`flex size-4 items-center justify-center rounded border text-[10px] ${i < 2 ? "border-action bg-action text-action-ink" : "border-line-strong"}`}>
              {i < 2 ? "✓" : ""}
            </span>
            Grade 5 · {s}
          </li>
        ))}
      </ul>
    ),
  },
  {
    title: "Build the question bank",
    teacher: "Review each draft question — approve, edit or reject — or write your own.",
    system:
      "AI drafts multiple-choice questions from that sub-strand's own curriculum text, and the server drops any that fail its checks. Nothing reaches a learner until a teacher approves it.",
    visual: (
      <div className="rounded-xl border border-line bg-surface p-3 text-sm">
        <p className="font-medium text-ink">Which of these is a good conductor of heat?</p>
        <div className="mt-2 grid grid-cols-2 gap-1.5 text-xs">
          {["Wood", "Copper ✓", "Plastic", "Wool"].map((o) => (
            <span key={o} className={`rounded-md border px-2 py-1 ${o.includes("✓") ? "border-ok/40 bg-ok-fill text-ok" : "border-line"}`}>
              {o}
            </span>
          ))}
        </div>
        <div className="mt-3 flex gap-2 text-xs">
          <span className="rounded-md bg-action px-2.5 py-1 text-action-ink">Approve</span>
          <span className="rounded-md border border-line-strong px-2.5 py-1">Edit</span>
        </div>
      </div>
    ),
  },
  {
    title: "Run a quiz",
    teacher: "Choose 5, 10 or 15 questions. Learners answer on a phone, or on a printed sheet you mark.",
    system: "Spreads the quiz from easy to hard and saves it, so the sheet and the marking grid match. The answer key never reaches the learner's device.",
    visual: (
      <div className="rounded-xl border border-line bg-surface p-3 text-sm">
        <div className="flex justify-between text-xs text-ink-muted">
          <span>Amina W.</span>
          <span>Question 3 of 10</span>
        </div>
        <div className="mt-2 h-1.5 rounded-full bg-sunken">
          <div className="h-1.5 w-[30%] rounded-full bg-action" />
        </div>
        <p className="mt-3 font-medium text-ink">Why does a metal spoon in hot tea get hot?</p>
      </div>
    ),
  },
  {
    title: "See each learner's level",
    teacher: "Open the class heatmap: every learner on every strand.",
    system:
      "IRT turns the answers into an ability on each strand, shown as KICD's four levels — or \"not enough evidence yet\" below five answers.",
    visual: (
      <div className="grid grid-cols-4 gap-1">
        {["below", "meets", "approaches", "exceeds", "meets", "meets", "below", "approaches"].map((k, i) => (
          <span key={i} className={`h-7 rounded ${TIER_BG[k as keyof typeof TIER_BG]}`} />
        ))}
      </div>
    ),
  },
  {
    title: "Support the learners who need it",
    teacher: "Start from the support list, then send a report home.",
    system:
      "Learners low on a strand twice in a row rise to the top. A short report in English and Kiswahili quotes the KICD curriculum word for word and is checked against it before it can be exported as a PDF.",
    visual: (
      <div className="space-y-1.5 text-sm">
        {["Baraka O. · Heat transfer", "Juma M. · Mixtures"].map((s) => (
          <div key={s} className="flex items-center justify-between rounded-xl border border-line bg-surface px-3 py-2">
            <span>{s}</span>
            <span className="text-xs text-ink-muted">Report ›</span>
          </div>
        ))}
      </div>
    ),
  },
];

export function HowItWorks() {
  const [open, setOpen] = useState(0);
  const step = STEPS[open];

  return (
    <div className="grid gap-6 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <ol className="space-y-2" aria-label="How Elimu Analytics works">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <button
              type="button"
              aria-current={i === open ? "step" : undefined}
              aria-controls="how-panel"
              onClick={() => setOpen(i)}
              className={`group flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all ${
                i === open
                  ? "border-action bg-surface shadow-lift"
                  : "border-line bg-transparent hover:border-line-strong hover:bg-surface"
              }`}
            >
              <span
                className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold transition-colors ${
                  i === open ? "bg-action text-action-ink" : "bg-sunken text-ink-muted"
                }`}
              >
                {i + 1}
              </span>
              <span className="text-[15px] font-medium text-ink">{s.title}</span>
            </button>
          </li>
        ))}
      </ol>

      <div
        id="how-panel"
        aria-live="polite"
        key={open}
        className="animate-[fade-up_300ms_ease-out] rounded-2xl border border-line bg-sunken p-5 sm:p-6"
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Step {open + 1}</p>
        <h3 className="mt-1 text-xl font-semibold tracking-tight text-ink">{step.title}</h3>
        <dl className="mt-4 space-y-3 text-[15px] leading-relaxed">
          <div>
            <dt className="font-semibold text-ink">You</dt>
            <dd className="text-ink-muted">{step.teacher}</dd>
          </div>
          <div>
            <dt className="font-semibold text-ink">Elimu</dt>
            <dd className="text-ink-muted">{step.system}</dd>
          </div>
        </dl>
        <div className="mt-5" aria-hidden="true">
          {step.visual}
        </div>
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            disabled={open === 0}
            onClick={() => setOpen(open - 1)}
            className="min-h-10 rounded-full border border-line-strong bg-surface px-4 text-sm font-medium text-ink disabled:opacity-40"
          >
            ‹ Back
          </button>
          <button
            type="button"
            disabled={open === STEPS.length - 1}
            onClick={() => setOpen(open + 1)}
            className="min-h-10 rounded-full bg-action px-4 text-sm font-medium text-action-ink disabled:opacity-40"
          >
            Next step ›
          </button>
        </div>
      </div>
    </div>
  );
}
