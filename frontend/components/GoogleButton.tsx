"use client";

/**
 * "Continue with Google", shown only when the server has Google configured.
 *
 * A plain link, not a fetch: signing in with Google is a full-page trip to
 * Google and back, and the server finishes it by setting the session cookie
 * and returning the browser to the app.
 *
 * Text only. Google's own mark is not drawn here.
 */

import { useEffect, useState } from "react";

export function GoogleButton() {
  const [offered, setOffered] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/providers")
      .then((r) => (r.ok ? r.json() : { google: false }))
      .then((p: { google?: boolean }) => !cancelled && setOffered(Boolean(p.google)))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!offered) return null;
  return (
    <div className="mt-6">
      <div className="flex items-center gap-3 text-sm text-ink-subtle">
        <span className="h-px flex-1 bg-line" />
        or
        <span className="h-px flex-1 bg-line" />
      </div>
      <a
        href="/api/auth/google/start"
        className="mt-6 flex min-h-11 w-full items-center justify-center rounded-md border
                   border-line-strong bg-surface px-4 text-[15px] font-medium text-ink
                   hover:bg-sunken"
      >
        Continue with Google
      </a>
    </div>
  );
}

/** What to tell a teacher Google sign-in turned away, by the server's reason. */
export const GOOGLE_REASONS: Record<string, string> = {
  not_registered:
    "That Google account isn’t on your school’s staff list. Ask your head teacher to add " +
    "the email you use with Google.",
  deactivated: "This account has been deactivated. Ask your head teacher.",
  other_google:
    "Your account is already linked to a different Google account. Use that one, or your " +
    "password.",
  cancelled: "Google sign-in was cancelled.",
  expired: "That sign-in took too long or was interrupted. Try again.",
  state: "That sign-in took too long or was interrupted. Try again.",
  invalid: "Google sign-in didn’t work this time. Try again, or use your password.",
  google_error: "Google sign-in didn’t work this time. Try again, or use your password.",
  not_configured: "Google sign-in isn’t set up on this server yet.",
};
