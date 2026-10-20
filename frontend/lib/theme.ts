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

/*
 * A tiny external store, read with React's useSyncExternalStore. That hook
 * stays in the component: this module is also imported by the root layout,
 * a server component, for THEME_BOOTSTRAP, and hooks cannot be imported
 * there.
 */
const listeners = new Set<() => void>();

export function subscribeTheme(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab changing the preference.
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** What the server render assumes: it cannot see this device's storage. */
export function serverTheme(): Theme {
  return "system";
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
  listeners.forEach((notify) => notify());
}

/**
 * Runs in <head> before the first paint. Without it, a teacher who chose dark
 * would see the page flash white on every load while React caught up.
 */
export const THEME_BOOTSTRAP =
  `try{var t=localStorage.getItem("${KEY}");` +
  `if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
