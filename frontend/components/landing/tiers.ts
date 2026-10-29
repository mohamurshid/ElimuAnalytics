import type { Level } from "@/lib/irt";

/** Literal class names, so Tailwind sees them. Tier colours mean a KICD level - nothing else. */
export const TIER_BG: Record<Level["key"], string> = {
  exceeds: "bg-tier-exceeds",
  meets: "bg-tier-meets",
  approaches: "bg-tier-approaches",
  below: "bg-tier-below",
};

export const TIER_ORDER: Level["key"][] = ["below", "approaches", "meets", "exceeds"];

export const TIER_SHORT: Record<Level["key"], string> = {
  exceeds: "Exceeds",
  meets: "Meets",
  approaches: "Approaches",
  below: "Below",
};
