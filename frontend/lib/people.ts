/** How a teacher is named on screen. Shared by the top bar and the profile. */

export const ROLE_LABEL: Record<string, string> = {
  teacher: "Teacher",
  school_admin: "Head teacher",
};

/** "Wanjiru Kamau" -> "WK". One word gives one letter. */
export function initials(name: string | undefined): string {
  if (!name) return "?";
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}
