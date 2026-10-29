/** How a teacher is named on screen. Shared by the top bar and the profile. */

export const ROLE_LABEL: Record<string, string> = {
  teacher: "Teacher",
  school_admin: "Head teacher",
};

/** "Wanjiru Kamau" -> "WK". One word gives one letter. */
export function initials(name: string | undefined): string {
  if (!name) return "?";
  // The first LETTER of each word: "Muhammad (second)" is "MS", not "M(" -
  // found 25 October with a teacher named that way.
  const letters = name
    .trim()
    .split(/\s+/)
    .map((w) => w.match(/\p{L}/u)?.[0] ?? "")
    .filter(Boolean)
    .slice(0, 2)
    .map((c) => c.toUpperCase())
    .join("");
  return letters || "?";
}

/** "Good morning" by the device's clock, for the line above a page title. */
export function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
