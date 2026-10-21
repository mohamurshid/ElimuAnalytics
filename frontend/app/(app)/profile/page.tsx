"use client";

/**
 * The signed-in teacher: who they are, which school, how the app looks,
 * their password, and signing out - here or everywhere.
 *
 * Password change and "sign out everywhere" arrived with teacher accounts
 * (21 October). Both end the teacher's other sessions at once, not when
 * their tokens happen to expire. A head teacher also reaches the staff list
 * from here.
 *
 * Sign-out sits near the top rather than at the bottom. It moved here from
 * the top bar, and school devices are shared - it should cost a teacher one
 * extra tap, not a search.
 */

import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { Button, ButtonLink, Card, Field, Note, PageHeader } from "@/components/ui";
import { changePassword, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { initials, ROLE_LABEL } from "@/lib/people";
import {
  applyTheme,
  readTheme,
  serverTheme,
  subscribeTheme,
  type Theme,
} from "@/lib/theme";

const THEMES: { value: Theme; label: string }[] = [
  { value: "system", label: "Same as phone" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export default function ProfilePage() {
  const { profile, signOut, signOutEverywhere } = useAuth();
  const router = useRouter();
  const [leaving, setLeaving] = useState(false);
  // Read from the device, not copied into state: localStorage does not exist
  // during the server render, so that render uses serverTheme() and React
  // swaps in the stored value on the client without an extra effect pass.
  const theme = useSyncExternalStore(subscribeTheme, readTheme, serverTheme);

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

        {profile.role !== "teacher" && (
          <Card className="p-4">
            <h2 className="text-base font-semibold text-ink">Teachers at your school</h2>
            <p className="mt-1 text-sm text-ink-muted">
              Add teachers, give them setup codes, and manage their accounts.
            </p>
            <ButtonLink href="/staff" variant="secondary" className="mt-3">
              Manage teachers
            </ButtonLink>
          </Card>
        )}

        <PasswordSection />

        <EverywhereSection
          onDone={() => router.replace("/login")}
          signOutEverywhere={signOutEverywhere}
        />

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
                onClick={() => applyTheme(option.value)}
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

function PasswordSection() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== again) {
      setError("The two new passwords are different.");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      setDone(true);
      setOpen(false);
      setCurrent("");
      setNext("");
      setAgain("");
    } catch (err) {
      setError(errorMessage(err, "Could not change the password"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="password-heading">
      <h2 id="password-heading" className="text-lg font-semibold text-ink">Password</h2>
      {done && (
        <div className="mt-2">
          <Note tone="ok">Password changed. Your other devices have been signed out.</Note>
        </div>
      )}
      {!open ? (
        <Button
          variant="secondary"
          className="mt-3"
          onClick={() => {
            setOpen(true);
            setDone(false);
          }}
        >
          Change password
        </Button>
      ) : (
        <form onSubmit={save} className="mt-3 space-y-4">
          <Field label="Current password" type="password" autoComplete="current-password"
                 required value={current} onChange={(e) => setCurrent(e.target.value)} />
          <Field label="New password" type="password" autoComplete="new-password" required
                 minLength={8} hint="At least 8 characters." value={next}
                 onChange={(e) => setNext(e.target.value)} />
          <Field label="New password again" type="password" autoComplete="new-password"
                 required value={again} onChange={(e) => setAgain(e.target.value)} />
          <Note tone="error">{error}</Note>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Change password"}</Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}

function EverywhereSection({
  onDone,
  signOutEverywhere,
}: {
  onDone: () => void;
  signOutEverywhere: () => Promise<void>;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    try {
      await signOutEverywhere();
    } finally {
      onDone();
    }
  }

  return (
    <section aria-labelledby="everywhere-heading">
      <h2 id="everywhere-heading" className="text-lg font-semibold text-ink">
        Signed in somewhere else?
      </h2>
      <p className="mt-1 text-sm text-ink-muted">
        For a lost phone, or one you shared. Ends every session on every device,
        this one included.
      </p>
      {!asking ? (
        <Button variant="secondary" className="mt-3" onClick={() => setAsking(true)}>
          Sign out everywhere
        </Button>
      ) : (
        <div role="alertdialog" aria-label="Sign out everywhere" className="mt-3 rounded-md bg-risk-fill p-3">
          <p className="text-[15px] text-ink">Sign out of every device, including this one?</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="danger" disabled={busy} onClick={go}>
              {busy ? "Signing out…" : "Sign out everywhere"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
