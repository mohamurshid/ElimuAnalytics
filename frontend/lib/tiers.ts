/**
 * KICD tiers, and how a cell is drawn.
 *
 * The four names are KICD's own wording from the curriculum designs, not
 * invented here, which is why they are matched as strings rather than mapped
 * to an internal enum - if the backend's wording ever changes, the mismatch
 * should be visible rather than silently absorbed.
 */

import type { CellStatus, DiagnosticCell } from "./types";

export const TIERS = [
  "Exceeds expectation",
  "Meets expectation",
  "Approaches expectation",
  "Below expectation",
] as const;

const VARIABLE: Record<string, string> = {
  "Exceeds expectation": "var(--tier-exceeds)",
  "Meets expectation": "var(--tier-meets)",
  "Approaches expectation": "var(--tier-approaches)",
  "Below expectation": "var(--tier-below)",
};

export function tierColour(tier: string | null): string {
  return (tier && VARIABLE[tier]) || "var(--tier-none)";
}

/** "Below expectation" -> "Below". The full phrase is in the legend. */
export function shortTier(tier: string | null): string {
  return tier ? tier.replace(/ expectation$/, "") : "no estimate";
}

export function statusLabel(status: CellStatus): string {
  return {
    estimated: "",
    provisional: "provisional",
    insufficient_evidence: "not enough evidence",
  }[status];
}

/** One line of plain English for a hover title, built from the API's own fields. */
export function cellTitle(cell: DiagnosticCell, learner: string): string {
  const head = `${learner} — ${cell.strand}`;
  if (cell.theta === null) return `${head}\n${cell.message}`;
  return `${head}\nθ ${cell.theta} · ${cell.tier}\n${cell.message}`;
}
