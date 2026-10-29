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

import { Icon } from "@/components/Icon";
import { Button, ButtonLink, Card, Field, IconTile, Note, PageHeader } from "@/components/ui";
import { errorMessage } from "@/lib/api";
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
        <Card className="overflow-hidden">
          <div className="flex items-center gap-4 bg-brand-fill/60 p-5">
            <span
              aria-hidden="true"
              className="flex size-16 shrink-0 items-center justify-center rounded-full
                         bg-action text-xl font-bold text-action-ink shadow-soft"
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
            person can’t see your classes. If you signed in with Google, sign out of
            Google on this device too - signing out here does not do that.
          </p>
        </section>

        {profile.role !== "teacher" && (
          <Card className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-5">
            <IconTile name="users" />
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold text-ink">Teachers at your school</h2>
              <p className="mt-0.5 text-sm text-ink-muted">
                Add teachers, give them setup codes, and manage their accounts.
              </p>
            </div>
            <ButtonLink href="/staff" variant="secondary">
              Manage teachers <Icon name="chevronRight" className="size-4" />
            </ButtonLink>
          </Card>
        )}

        <PasswordSection hasPassword={profile.has_password} />

        <EverywhereSection
          onDone={() => router.replace("/login")}
          signOutEverywhere={signOutEverywhere}
        />

        <section aria-labelledby="appearance-heading" className="rounded-2xl border border-line bg-surface p-4 shadow-soft sm:p-5">
          <h2 id="appearance-heading" className="flex items-center gap-3 text-lg font-semibold text-ink">
            <IconTile name="sparkles" size="sm" />
            Appearance
          </h2>
          <p className="mt-1 text-sm text-ink-muted">Saved on this device only.</p>
          <div
            role="radiogroup"
            aria-labelledby="appearance-heading"
            className="mt-3 grid grid-cols-3 gap-1 rounded-xl bg-sunken p-1"
          >
            {THEMES.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={theme === option.value}
                onClick={() => applyTheme(option.value)}
                className={`min-h-11 rounded-lg px-2 text-sm font-semibold transition-all
                            ${theme === option.value
                              ? "bg-surface text-ink shadow-soft"
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

/**
 * Change the password - or, for a teacher who has only signed in with Google,
 * set a first one (24 October). Such a teacher has no current password to
 * give, so the field is left out and the button says what it does.
 */
function PasswordSection({ hasPassword }: { hasPassword: boolean }) {
  const { changePassword } = useAuth();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"changed" | "set" | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (next !== again) {
      setError("The two new passwords are different.");
      return;
    }
    setBusy(true);
    try {
      await changePassword(hasPassword ? current : null, next);
      setDone(hasPassword ? "changed" : "set");
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
    <section aria-labelledby="password-heading" className="rounded-2xl border border-line bg-surface p-4 shadow-soft sm:p-5">
      <h2 id="password-heading" className="flex items-center gap-3 text-lg font-semibold text-ink">
        <IconTile name="lock" size="sm" />
        Password
      </h2>
      {!hasPassword && !done && (
        <p className="mt-1 text-sm text-ink-muted">
          You sign in with Google. A password lets you sign in without it, and unlock quiz
          mode if you forget the PIN.
        </p>
      )}
      {done && (
        <div className="mt-2">
          <Note tone="ok">
            {done === "set" ? "Password set." : "Password changed."} Your other devices have
            been signed out.
          </Note>
        </div>
      )}
      {!open ? (
        <Button
          variant="secondary"
          className="mt-3"
          onClick={() => {
            setOpen(true);
            setDone(null);
          }}
        >
          {hasPassword ? "Change password" : "Set a password"}
        </Button>
      ) : (
        <form onSubmit={save} className="mt-3 space-y-4">
          {hasPassword && (
            <Field label="Current password" type="password" autoComplete="current-password"
                   required value={current} onChange={(e) => setCurrent(e.target.value)} />
          )}
          <Field label="New password" type="password" autoComplete="new-password" required
                 minLength={8} hint="At least 8 characters." value={next}
                 onChange={(e) => setNext(e.target.value)} />
          <Field label="New password again" type="password" autoComplete="new-password"
                 required value={again} onChange={(e) => setAgain(e.target.value)} />
          <Note tone="error">{error}</Note>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? "Saving…" : hasPassword ? "Change password" : "Set password"}
            </Button>
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
    <section aria-labelledby="everywhere-heading" className="rounded-2xl border border-line bg-surface p-4 shadow-soft sm:p-5">
      <h2 id="everywhere-heading" className="flex items-center gap-3 text-lg font-semibold text-ink">
        <IconTile name="phone" size="sm" />
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
        <div role="alertdialog" aria-label="Sign out everywhere" className="mt-3 rounded-xl bg-risk-fill p-4">
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
