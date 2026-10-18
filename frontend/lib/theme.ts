/**
 * Light, dark, or whatever the phone is set to.
 *
 * Stored per device in localStorage, which is the right home for a display
 * preference: it belongs to this screen, not to the account, and losing it
 * costs nothing but a tap. Every access is wrapped, because storage can be
 * unavailable in a private window and a theme must never break a page.
 */

export type Theme = "system" | "light" | "dark";

const KEY = "elimu-theme";

export function readTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // Preference not saved; it still applies until the page is reloaded.
  }
}

/**
 * Runs in <head> before the first paint. Without it, a teacher who chose dark
 * would see the page flash white on every load while React caught up.
 */
export const THEME_BOOTSTRAP =
  `try{var t=localStorage.getItem("${KEY}");` +
  `if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
