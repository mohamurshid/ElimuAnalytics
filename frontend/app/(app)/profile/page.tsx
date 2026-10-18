"use client";

/**
 * The signed-in teacher: who they are, which school, how the app looks, and
 * signing out.
 *
 * Read-only by decision. Changing a password and signing out of other devices
 * need endpoints that belong with teacher-account creation, which UAT needs
 * anyway; building them twice would be waste. Nothing here pretends to edit
 * what it cannot.
 *
 * Sign-out sits near the top rather than at the bottom. It moved here from
 * the top bar, and school devices are shared - it should cost a teacher one
 * extra tap, not a search.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, Card, PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { initials, ROLE_LABEL } from "@/lib/people";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "Same as phone" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function ProfilePage() {
  const { profile, signOut } = useAuth();
  const router = useRouter();
  const [theme, setTheme] = useState<Theme>("system");
  const [leaving, setLeaving] = useState(false);

  // Read after mount: localStorage does not exist during the server render.
  useEffect(() => setTheme(readTheme()), []);

  function choose(next: Theme) {
    setTheme(next);
    applyTheme(next);
  }

  async function handleSignOut() {
    setLeaving(true);
    try {
      await signOut();
    } finally {
      router.replace("/login");
    }
  }

  if (!profile) return null; // the guard is redirecting

  const role = ROLE_LABEL[profile.role] ?? profile.role;

  return (
    <>
      <PageHeader title="Profile" />

      <div className="space-y-6">
        <Card>
          <div className="flex items-center gap-4 p-5">
            <span
              aria-hidden="true"
              className="flex size-14 shrink-0 items-center justify-center rounded-full
                         border border-line-strong bg-sunken text-lg font-semibold text-ink"
            >
              {initials(profile.name)}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-lg font-semibold text-ink">
                {profile.name}
              </span>
              <span className="block text-[15px] text-ink-muted">{role}</span>
            </span>
          </div>
          <dl className="divide-y divide-line border-t border-line">
            {[
              ["Email", profile.email],
              ["School", profile.school || "—"],
            ].map(([label, value]) => (
              <div key={label} className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 px-5 py-3.5">
                <dt className="text-[15px] text-ink-muted">{label}</dt>
                <dd className="min-w-0 break-words text-[15px] font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>

        <section aria-labelledby="signout-heading">
          <h2 id="signout-heading" className="sr-only">Sign out</h2>
          <Button
            variant="secondary"
            className="w-full sm:w-auto"
            disabled={leaving}
            onClick={handleSignOut}
          >
            {leaving ? "Signing out…" : "Sign out"}
          </Button>
          <p className="mt-2 text-sm text-ink-subtle">
            Sharing this phone or tablet? Sign out when you finish, so the next
            person can’t see your classes.
          </p>
        </section>

        <section aria-labelledby="appearance-heading">
          <h2 id="appearance-heading" className="text-lg font-semibold text-ink">
            Appearance
          </h2>
          <p className="mt-1 text-sm text-ink-muted">Saved on this device only.</p>
          <div
            role="radiogroup"
            aria-labelledby="appearance-heading"
            className="mt-3 grid grid-cols-3 gap-1 rounded-md border border-line-strong bg-surface p-1"
          >
            {THEMES.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={theme === option.value}
                onClick={() => choose(option.value)}
                className={`min-h-11 rounded px-2 text-sm font-medium
                            ${theme === option.value
                              ? "bg-sunken text-ink"
                              : "text-ink-muted hover:text-ink"}`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
