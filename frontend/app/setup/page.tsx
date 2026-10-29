"use client";

/**
 * Setting up an account with a head teacher's one-time code.
 *
 * A head teacher adds a teacher and passes on a code like K7P4-2QXA; the
 * teacher comes here, enters their email, the code and a password of their
 * own, and is signed in. The same page serves a teacher who has forgotten
 * their password and been given a new code.
 *
 * The code is forgiving about how it is typed - case, spaces and the dash -
 * because it is read aloud or copied from paper.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { GoogleButton } from "@/components/GoogleButton";
import { Icon } from "@/components/Icon";
import { SiteHeader } from "@/components/SiteHeader";
import { Button, Field, Note } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/routes";

const MIN_PASSWORD = 8;

export default function SetupPage() {
  const { profile, resolved, setUp } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (resolved && profile) router.replace(HOME);
  }, [resolved, profile, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(`Choose a password of at least ${MIN_PASSWORD} characters.`);
      return;
    }
    if (password !== again) {
      setError("The two passwords are different.");
      return;
    }
    setBusy(true);
    try {
      await setUp(email, code, password);
      router.replace(HOME);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not reach the server. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <SiteHeader current="setup" />
    <main className="relative isolate flex min-h-[calc(100dvh-4rem)] flex-col overflow-hidden px-5 pt-8 pb-8 sm:items-center sm:justify-center sm:px-4">
      {/* A soft wash of the brand behind the card; decoration only. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 -top-40 -z-10 mx-auto h-[28rem] max-w-3xl rounded-full opacity-70 blur-3xl"
        style={{ background: "radial-gradient(closest-side, var(--brand-fill), transparent)" }}
      />
      <div className="w-full sm:max-w-sm">

        <form
          onSubmit={submit}
          className="mt-2 sm:mt-0 sm:rounded-3xl sm:border sm:border-line sm:bg-surface sm:p-7 sm:shadow-lift"
        >
          <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-fill text-brand-strong">
            <Icon name="lock" className="size-6" />
          </span>
          <h1 className="text-[28px] font-bold tracking-tight text-ink">Set up your account</h1>
          <p className="mt-1.5 text-[15px] leading-relaxed text-ink-muted">
            Use the code your head teacher gave you, and choose your own password.
          </p>

          <div className="mt-7 space-y-5">
            <Field
              label="Email"
              id="email"
              name="email"
              type="email"
              inputMode="email"
              required
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Field
              label="Setup code"
              id="code"
              name="code"
              required
              autoComplete="one-time-code"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="ABCD-EFGH"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Field
              label="New password"
              id="password"
              name="password"
              type="password"
              required
              minLength={MIN_PASSWORD}
              autoComplete="new-password"
              hint={`At least ${MIN_PASSWORD} characters.`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Field
              label="New password again"
              id="again"
              name="again"
              type="password"
              required
              autoComplete="new-password"
              value={again}
              onChange={(e) => setAgain(e.target.value)}
            />
          </div>

          {error && (
            <div className="mt-5">
              <Note tone="error">{error}</Note>
            </div>
          )}

          <Button type="submit" disabled={busy} className="mt-7 w-full">
            {busy ? "Setting up…" : "Set up and sign in"}
          </Button>

          {/* A teacher whose head teacher added their Google email needs no
              code at all. */}
          <GoogleButton />
        </form>

        <p className="mt-6 text-center text-[15px] text-ink-muted">
          Already set up?{" "}
          <Link href="/login" className="font-semibold text-brand-strong underline underline-offset-2">
            Sign in
          </Link>
        </p>
      </div>
    </main>
    </>
  );
}
