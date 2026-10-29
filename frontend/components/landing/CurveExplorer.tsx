"use client";

/**
 * "How one question behaves": the item characteristic curve, live.
 *
 * Difficulty slides the curve left and right; discrimination makes it steep
 * or flat; the learner's ability is a point on it. Underneath, the ability
 * axis is banded by KICD level with the server's own cut-offs, so the picture
 * ties the maths to what a teacher sees.
 */

import { useId, useState } from "react";

import { LEVELS, levelFor, pCorrect } from "@/lib/irt";

const W = 360;
const H = 220;
const PAD = { left: 34, right: 12, top: 14, bottom: 40 };
const X0 = -4;
const X1 = 4;
const x = (t: number) => PAD.left + ((t - X0) / (X1 - X0)) * (W - PAD.left - PAD.right);
const y = (p: number) => PAD.top + (1 - p) * (H - PAD.top - PAD.bottom);

const PRESETS = [
  { name: "An easy question", a: 1.3, b: -1.5 },
  { name: "A hard question", a: 1.3, b: 1.5 },
  { name: "A question that tells you little", a: 0.3, b: 0 },
];

export function CurveExplorer() {
  const [a, setA] = useState(1.3);
  const [b, setB] = useState(0);
  const [theta, setTheta] = useState(0.5);
  const ids = { a: useId(), b: useId(), t: useId() };

  const p = pCorrect(theta, a, b);
  const curve = Array.from({ length: 81 }, (_, i) => {
    const t = X0 + (i / 80) * (X1 - X0);
    return `${i ? "L" : "M"}${x(t).toFixed(1)} ${y(pCorrect(t, a, b)).toFixed(1)}`;
  }).join(" ");
  const level = levelFor(theta);

  // Level bands along the ability axis, lowest first.
  const bands = [...LEVELS].reverse().map((l, i, all) => ({
    key: l.key,
    from: Math.max(X0, l.from),
    to: i + 1 < all.length ? all[i + 1].from : X1,
  }));

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-center">
      <div className="rounded-2xl border border-line bg-surface p-3 sm:p-4">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Chance of a correct answer against ability. At ability ${theta.toFixed(1)} the chance is ${Math.round(p * 100)} percent.`}
          className="h-auto w-full"
        >
          {bands.map((band) => (
            <rect
              key={band.key}
              x={x(band.from)}
              y={H - PAD.bottom + 8}
              width={x(band.to) - x(band.from)}
              height={8}
              rx={2}
              fill={`var(--tier-${band.key})`}
            />
          ))}
          {[0, 0.5, 1].map((v) => (
            <g key={v}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(v)}
                y2={y(v)}
                stroke="var(--border)"
                strokeDasharray={v === 0.5 ? "3 3" : undefined}
              />
              <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" fontSize="10" fill="var(--subtle)">
                {v * 100}%
              </text>
            </g>
          ))}
          {/* Difficulty: where the curve crosses 50%. */}
          <line x1={x(b)} x2={x(b)} y1={y(0.5)} y2={H - PAD.bottom} stroke="var(--border-strong)" strokeDasharray="2 3" />
          <path d={curve} fill="none" stroke="var(--foreground)" strokeWidth={2.5} strokeLinecap="round" />
          <line x1={x(theta)} x2={x(theta)} y1={y(p)} y2={H - PAD.bottom} stroke="var(--tier-meets)" strokeWidth={1.5} />
          <circle cx={x(theta)} cy={y(p)} r={6} fill="var(--surface)" stroke="var(--tier-meets)" strokeWidth={3} className="transition-all duration-150" />
          {[-3, -2, -1, 0, 1, 2, 3].map((t) => (
            <text key={t} x={x(t)} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--subtle)">
              {t}
            </text>
          ))}
          <text x={W - PAD.right} y={H - PAD.bottom - 6} textAnchor="end" fontSize="10" fill="var(--muted)">
            ability →
          </text>
        </svg>
        <p aria-live="polite" className="mt-2 px-1 text-[15px] leading-relaxed text-ink">
          A learner at ability <strong className="tabular-nums">{theta.toFixed(1).replace("-", "−")}</strong> ({level.label.toLowerCase()})
          has a{" "}
          <strong className="tabular-nums">{Math.round(p * 100)}%</strong> chance of answering this question
          correctly.
        </p>
      </div>

      <div className="space-y-5">
        <Slider
          id={ids.t}
          label="The learner's ability"
          hint="Move the learner along the scale. The band under the chart shows the KICD level."
          min={-3}
          max={3}
          step={0.1}
          value={theta}
          onChange={setTheta}
        />
        <Slider
          id={ids.b}
          label="Question difficulty"
          hint="Where the curve crosses 50%. Harder questions sit further right."
          min={-2.5}
          max={2.5}
          step={0.1}
          value={b}
          onChange={setB}
        />
        <Slider
          id={ids.a}
          label="Question discrimination"
          hint="How steeply the curve rises. A steep question separates learners just below its difficulty from those just above. Elimu flags questions below 0.3."
          min={0.2}
          max={2.5}
          step={0.1}
          value={a}
          onChange={setA}
        />
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((pr) => (
            <button
              key={pr.name}
              type="button"
              onClick={() => {
                setA(pr.a);
                setB(pr.b);
              }}
              className="min-h-10 rounded-full border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink transition-colors hover:bg-sunken"
            >
              {pr.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Slider({
  id,
  label,
  hint,
  min,
  max,
  step,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[15px] font-semibold text-ink">
          {label}
        </label>
        <span className="tabular-nums text-sm text-ink-muted">{value.toFixed(1)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-describedby={`${id}-hint`}
        className="mt-2 h-2 w-full cursor-pointer accent-[var(--action)]"
      />
      <p id={`${id}-hint`} className="mt-1.5 text-sm leading-relaxed text-ink-muted">
        {hint}
      </p>
    </div>
  );
}
