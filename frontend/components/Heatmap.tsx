"use client";

/**
 * A class's levels: a summary bar per strand, then learners against strands.
 *
 * Three things this has to get right, in order of how badly they go wrong:
 *
 * **An absent estimate must look deliberate.** A learner below the evidence
 * threshold gets a hatched neutral cell reading "no level yet", with the count
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
 *
 * And two things changed for teachers: theta is no longer printed in the
 * cells - it is a model estimate, and a number in a cell gets read as a mark -
 * though it stays in the hover title for anyone looking for it; and learners
 * sort by need, so the ones to act on are at the top rather than scattered
 * through an alphabetical list.
 */

import Link from "next/link";

import { cellTitle, shortTier, tierColour, TIERS } from "@/lib/tiers";
import type { DiagnosticCell, Heatmap as HeatmapData, LearnerDiagnostics } from "@/lib/types";

const HATCH =
  "repeating-linear-gradient(45deg," +
  " color-mix(in oklab, var(--tier-none) 35%, transparent) 0 3px," +
  " transparent 3px 6px)";

/** Below first. No estimate sorts after every estimated level. */
const RANK: Record<string, number> = {
  "Below expectation": 0,
  "Approaches expectation": 1,
  "Meets expectation": 2,
  "Exceeds expectation": 3,
};
const NO_LEVEL = 4;

function rankOf(cell: DiagnosticCell | undefined): number {
  return cell?.tier != null && cell.tier in RANK ? RANK[cell.tier] : NO_LEVEL;
}

/** Most need first: worst level across strands, then how many strands share it. */
export function byNeed(a: LearnerDiagnostics, b: LearnerDiagnostics): number {
  const worst = (l: LearnerDiagnostics) =>
    l.cells.length ? Math.min(...l.cells.map(rankOf)) : NO_LEVEL;
  const count = (l: LearnerDiagnostics, r: number) =>
    l.cells.filter((c) => rankOf(c) === r).length;
  const wa = worst(a);
  const wb = worst(b);
  if (wa !== wb) return wa - wb;
  const ca = count(a, wa);
  const cb = count(b, wb);
  if (ca !== cb) return cb - ca;
  return a.name.localeCompare(b.name);
}

export function Legend({ minimum }: { minimum: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-muted">
      {[...TIERS].reverse().map((tier) => (
        <span key={tier} className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block size-3 rounded-sm"
            style={{ background: tierColour(tier) }}
          />
          {tier}
        </span>
      ))}
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block size-3 rounded-sm border border-line-strong"
          style={{ backgroundImage: HATCH }}
        />
        No level yet — fewer than {minimum} answers
      </span>
    </div>
  );
}

/**
 * How the class is spread across the levels, one bar per strand.
 *
 * The counts are printed under the bar, not just implied by segment widths:
 * a width is hard to read exactly and impossible to read in greyscale.
 */
export function ClassSummary({ data }: { data: HeatmapData }) {
  return (
    <div className="space-y-5">
      {data.strands.map((strand) => {
        const counts = [0, 0, 0, 0, 0];
        for (const learner of data.learners) {
          const cell = learner.cells.find((c) => c.strand_id === strand.strand_id);
          counts[rankOf(cell)] += 1;
        }
        const total = counts.reduce((a, b) => a + b, 0) || 1;
        const parts = [
          { label: "Below", n: counts[0], colour: tierColour("Below expectation") },
          { label: "Approaches", n: counts[1], colour: tierColour("Approaches expectation") },
          { label: "Meets", n: counts[2], colour: tierColour("Meets expectation") },
          { label: "Exceeds", n: counts[3], colour: tierColour("Exceeds expectation") },
          { label: "No level yet", n: counts[4], colour: "var(--tier-none)" },
        ];
        const [strandName, sub] = strand.name.split(" / ");
        const summary = parts.map((p) => `${p.n} ${p.label}`).join(", ");
        return (
          <div key={strand.strand_id}>
            <p className="text-[15px] font-semibold text-ink">{sub ?? strandName}</p>
            {sub && <p className="text-sm text-ink-subtle">{strandName}</p>}
            <div
              role="img"
              aria-label={`${sub ?? strandName}: ${summary}`}
              className="mt-2.5 flex h-3 overflow-hidden rounded-full bg-sunken"
            >
              {parts.map((p) =>
                p.n > 0 ? (
                  <span
                    key={p.label}
                    style={{
                      width: `${(p.n / total) * 100}%`,
                      background: p.colour,
                      backgroundImage: p.label === "No level yet" ? HATCH : undefined,
                    }}
                  />
                ) : null,
              )}
            </div>
            <dl className="mt-2.5 grid grid-cols-5 gap-1 text-center">
              {parts.map((p) => (
                <div key={p.label}>
                  <dt className="text-xs leading-tight text-ink-subtle">{p.label}</dt>
                  <dd className="text-base font-semibold tabular-nums text-ink">{p.n}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })}
    </div>
  );
}

export function Heatmap({
  data,
  order = "need",
}: {
  data: HeatmapData;
  order?: "need" | "name";
}) {
  const learners = [...data.learners].sort(
    order === "need" ? byNeed : (a, b) => a.name.localeCompare(b.name),
  );

  return (
    <div className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0">
      <table className="w-full border-separate border-spacing-y-1 text-[15px]">
        <caption className="sr-only">
          Level by learner and strand. Each cell gives the KICD level in words;
          cells without enough evidence are marked “no level yet”.
        </caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 z-10 bg-canvas py-2 pr-3 text-left text-sm font-medium text-ink-muted"
            >
              Learner
            </th>
            {data.strands.map((strand) => {
              const [strandName, sub] = strand.name.split(" / ");
              return (
                <th
                  key={strand.strand_id}
                  scope="col"
                  className="min-w-36 px-1 py-2 text-left text-sm font-medium text-ink-muted"
                >
                  {sub ?? strandName}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {learners.map((learner) => (
            <tr key={learner.student_id}>
              <th
                scope="row"
                className="sticky left-0 z-10 bg-canvas py-0 pr-3 text-left font-normal whitespace-nowrap"
              >
                <Link
                  href={`/students/${learner.student_id}`}
                  className="inline-flex min-h-12 items-center font-medium text-ink hover:underline"
                >
                  {learner.name}
                </Link>
              </th>

              {data.strands.map((strand) => {
                const cell = learner.cells.find((c) => c.strand_id === strand.strand_id);

                if (!cell) {
                  return (
                    <td key={strand.strand_id} className="px-1 text-sm text-ink-subtle">
                      —
                    </td>
                  );
                }

                const none = cell.status === "insufficient_evidence";
                const provisional = cell.status === "provisional";
                return (
                  <td key={strand.strand_id} className="px-1 align-middle">
                    <Link
                      href={`/students/${learner.student_id}`}
                      title={cellTitle(cell, learner.name)}
                      className="tier-cell flex min-h-12 flex-col justify-center rounded-r-md px-3"
                      style={{
                        ["--tier" as string]: tierColour(cell.tier),
                        backgroundImage: none ? HATCH : undefined,
                      }}
                    >
                      <span className={`leading-tight ${none ? "text-ink-muted" : "font-semibold text-ink"}`}>
                        {none ? "No level yet" : shortTier(cell.tier)}
                      </span>
                      {(none || provisional) && (
                        <span className="text-xs leading-tight text-ink-subtle">
                          {none
                            ? `${cell.answered} of ${data.minimum_responses} answers`
                            : `provisional · ${cell.answered} answers`}
                        </span>
                      )}
                    </Link>
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
