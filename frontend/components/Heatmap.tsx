"use client";

/**
 * Learners down, strands across.
 *
 * Three things this has to get right, in order of how badly they go wrong:
 *
 * **An absent estimate must look deliberate.** A learner below the evidence
 * threshold gets a hatched neutral cell reading "no estimate", with the count
 * so far. A blank would read as a rendering fault, and the whole point of the
 * threshold is that the refusal is a finding, not a gap in the data.
 *
 * **Colour is never the only signal.** Every cell carries the tier in words,
 * the band at its left edge darkens with need, and the tint drops out in
 * print and forced-colours leaving band and text. A greyscale thesis page
 * still ranks correctly.
 *
 * **Darker means more need, not less ability.** Encoding "ability" would put
 * the heaviest ink on the learners who need nothing. The cells a teacher must
 * act on are the ones that carry weight.
 */

import Link from "next/link";

import { cellTitle, shortTier, statusLabel, tierColour, TIERS } from "@/lib/tiers";
import type { Heatmap as HeatmapData } from "@/lib/types";

export function Legend({ minimum }: { minimum: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs
                    text-neutral-600">
      {TIERS.map((tier) => (
        <span key={tier} className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-3 w-3 rounded-sm"
            style={{ background: tierColour(tier) }}
          />
          {tier}
        </span>
      ))}
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block h-3 w-3 rounded-sm border border-neutral-400"
          style={{
            backgroundImage:
              "repeating-linear-gradient(45deg, var(--tier-none) 0 2px," +
              " transparent 2px 4px)",
          }}
        />
        No estimate — fewer than {minimum} items answered
      </span>
    </div>
  );
}

export function Heatmap({ data }: { data: HeatmapData }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0.5 text-sm">
        <caption className="sr-only">
          Estimated competency by learner and strand. Each cell gives the KICD
          tier in words; cells without enough evidence are marked “no estimate”.
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 z-10 bg-[var(--background)] px-2 py-2
                         text-left font-medium"
            >
              Learner
            </th>
            {data.strands.map((strand) => (
              <th
                key={strand.strand_id}
                scope="col"
                className="min-w-40 px-2 py-2 text-left font-medium"
              >
                {strand.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.learners.map((learner) => (
            <tr key={learner.student_id}>
              <th
                scope="row"
                className="sticky left-0 z-10 bg-[var(--background)] px-2 py-2
                           text-left font-normal whitespace-nowrap"
              >
                <Link
                  href={`/students/${learner.student_id}`}
                  className="underline underline-offset-2 hover:text-neutral-500"
                >
                  {learner.name}
                </Link>
              </th>

              {data.strands.map((strand) => {
                const cell = learner.cells.find(
                  (c) => c.strand_id === strand.strand_id,
                );

                if (!cell) {
                  return (
                    <td
                      key={strand.strand_id}
                      className="px-2 py-2 text-xs text-neutral-500"
                    >
                      —
                    </td>
                  );
                }

                const none = cell.status === "insufficient_evidence";
                return (
                  <td
                    key={strand.strand_id}
                    title={cellTitle(cell, learner.name)}
                    className="tier-cell px-2 py-1.5 align-top"
                    style={{
                      ["--tier" as string]: tierColour(cell.tier),
                      backgroundImage: none
                        ? "repeating-linear-gradient(45deg," +
                          " color-mix(in oklab, var(--tier-none) 35%, transparent) 0 3px," +
                          " transparent 3px 6px)"
                        : undefined,
                    }}
                  >
                    <span className="block font-medium">
                      {shortTier(cell.tier)}
                    </span>
                    <span className="block text-xs text-neutral-600">
                      {cell.theta === null
                        ? `${cell.answered} of ${data.minimum_responses} items`
                        : `θ ${cell.theta.toFixed(2)}`}
                      {statusLabel(cell.status) && cell.theta !== null
                        ? ` · ${statusLabel(cell.status)}`
                        : ""}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
