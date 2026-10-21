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
import { Logo } from "@/components/Logo";
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
    <main className="flex min-h-screen flex-col px-5 pt-10 pb-8 sm:items-center sm:justify-center sm:px-4 sm:pt-8">
      <div className="w-full sm:max-w-sm">
        <Logo />

        <form
          onSubmit={submit}
          className="mt-10 sm:mt-6 sm:rounded-lg sm:border sm:border-line sm:bg-surface sm:p-6"
        >
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Set up your account</h1>
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
          <Link href="/login" className="font-medium text-ink underline underline-offset-2">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
