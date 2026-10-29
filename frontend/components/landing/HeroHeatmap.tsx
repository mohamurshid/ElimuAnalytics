"use client";

/**
 * The hero's picture: a class heatmap that slowly changes, as levels do
 * when learners are taught and quizzed again. Illustrative only - invented
 * names, no real data - and it stands still for anyone who has asked their
 * device for reduced motion.
 */

import { useEffect, useState } from "react";

import { TIER_BG, TIER_ORDER, TIER_SHORT } from "./tiers";

const LEARNERS = ["Amina W.", "Baraka O.", "Chebet K.", "Juma M.", "Wanjiru N.", "Otieno J."];
const STRANDS = ["Heat", "Light", "Mixtures", "Money", "Area"];

// Tier index 0-3 (Below .. Exceeds), or -1 for "no level yet". Fixed, so the
// server and the browser draw the same first frame.
const START: number[][] = [
  [2, 3, 2, 1, 2],
  [0, 1, -1, 1, 0],
  [3, 2, 3, 2, 3],
  [1, 0, 1, 2, 1],
  [2, 2, 1, -1, 2],
  [1, 2, 0, 1, 1],
];

export function HeroHeatmap() {
  const [cells, setCells] = useState(START);
  const [moved, setMoved] = useState<string | null>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let settle: number | undefined;
    const id = window.setInterval(() => {
      const r = Math.floor(Math.random() * START.length);
      const c = Math.floor(Math.random() * START[0].length);
      // Mostly upward: teaching works more often than not.
      const up = Math.random() < 0.7;
      setCells((grid) => {
        const now = grid[r][c];
        const next = now < 0 ? 1 : Math.max(0, Math.min(3, now + (up ? 1 : -1)));
        if (next === now) return grid;
        return grid.map((row, i) => (i === r ? row.map((v, j) => (j === c ? next : v)) : row));
      });
      setMoved(`${r}:${c}`);
      window.clearTimeout(settle);
      settle = window.setTimeout(() => setMoved(null), 700);
    }, 1400);
    return () => {
      window.clearInterval(id);
      window.clearTimeout(settle);
    };
  }, []);

  return (
    <figure
      className="relative rounded-2xl border border-line bg-surface p-4 shadow-[0_1px_0_var(--border),0_24px_48px_-24px_rgba(13,54,107,0.35)] sm:p-5"
      aria-label="Illustration: a class heatmap of six learners across five strands, coloured by KICD level"
    >
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-semibold text-ink">Grade 5 Blue</p>
        <p className="text-xs text-ink-subtle">Levels by strand</p>
      </div>

      <div aria-hidden="true" className="mt-4 grid grid-cols-[5.5rem_repeat(5,minmax(0,1fr))] gap-1.5 text-[11px]">
        <span />
        {STRANDS.map((s) => (
          <span key={s} className="truncate text-center font-medium text-ink-muted">
            {s}
          </span>
        ))}
        {LEARNERS.map((name, r) => (
          <Row key={name} name={name} values={cells[r]} row={r} moved={moved} />
        ))}
      </div>

      <figcaption className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-ink-muted">
        {[...TIER_ORDER].reverse().map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={`size-2.5 rounded-sm ${TIER_BG[k]}`} />
            {TIER_SHORT[k]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm border border-dashed border-line-strong" />
          No level yet
        </span>
      </figcaption>
      <p className="mt-2 text-[11px] text-ink-subtle">Illustration, not real learners.</p>
    </figure>
  );
}

function Row({
  name,
  values,
  row,
  moved,
}: {
  name: string;
  values: number[];
  row: number;
  moved: string | null;
}) {
  return (
    <>
      <span className="truncate self-center pr-1 text-ink">{name}</span>
      {values.map((v, c) => {
        const key = v < 0 ? null : TIER_ORDER[v];
        const pulse = moved === `${row}:${c}`;
        return (
          <span
            key={c}
            className={`h-7 rounded-md transition-[background-color,transform] duration-700 ease-out sm:h-8 ${
              key ? TIER_BG[key] : "border border-dashed border-line-strong"
            } ${pulse ? "scale-110" : "scale-100"}`}
          />
        );
      })}
    </>
  );
}
