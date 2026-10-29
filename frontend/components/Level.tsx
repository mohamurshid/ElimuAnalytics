/**
 * A KICD level as a chip: a dot in the level's colour and its name in
 * words, on a tint of the same colour. Colour is never the only signal - the
 * word is always there - and text sits on the tint, not on the ramp colour,
 * so contrast holds at every level and in dark mode.
 */

import { shortTier, tierColour } from "@/lib/tiers";

export function LevelChip({
  tier,
  size = "md",
  label,
}: {
  tier: string | null;
  size?: "sm" | "md";
  /** Overrides the words, e.g. "No level yet". */
  label?: string;
}) {
  const colour = tierColour(tier);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold text-ink
                  ${size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"}`}
      style={{ background: `color-mix(in oklab, ${colour} 16%, var(--surface))` }}
    >
      <span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ background: colour }} />
      {label ?? shortTier(tier)}
    </span>
  );
}

/** A learner's initials in a circle tinted by their level. */
export function LevelAvatar({
  name,
  tier,
  size = "md",
}: {
  name: string;
  tier: string | null;
  size?: "sm" | "md";
}) {
  const colour = tierColour(tier);
  const letters = name
    .split(/\s+/)
    .map((w) => w.match(/\p{L}/u)?.[0] ?? "")
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center rounded-full font-bold text-ink ${size === "sm" ? "size-8 text-xs" : "size-11 text-sm"}`}
      style={{
        background: `color-mix(in oklab, ${colour} 18%, var(--surface))`,
        boxShadow: `inset 0 0 0 2px ${colour}`,
      }}
    >
      {letters || "?"}
    </span>
  );
}
