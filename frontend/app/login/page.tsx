"use client";

/**
 * Sign-in.
 *
 * The first screen a UAT teacher sees, so it says in one line what the
 * product is for, in their terms. "Continue with Google" appears only when
 * the server has Google configured - a button that does nothing is worse
 * than its absence - and a teacher Google turned away is told why, from the
 * reason the server put in the address.
 *
 * A teacher a head teacher has just added has no password yet; the link
 * under the form takes them to set one up with their code.
 *
 * On a phone the form fills the screen without a card around it - a bordered
 * box on a 360px screen only wastes the margin. From sm up it becomes a card.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { GOOGLE_REASONS, GoogleButton } from "@/components/GoogleButton";
import { Logo } from "@/components/Logo";
import { Button, Field, Note } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/routes";

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary above it in the App Router.
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}

function SignIn() {
  const { profile, resolved, signIn } = useAuth();
  const router = useRouter();
  const googleReason = useSearchParams().get("google");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in - a reload landed here, or the back button did.
  useEffect(() => {
    if (resolved && profile) router.replace(HOME);
  }, [resolved, profile, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email, password);
      router.replace(HOME);
    } catch (e) {
      // 429 is the login throttle, and says when to come back. Showing the
      // server's own message avoids inventing a second vocabulary for it.
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
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h1>
          <p className="mt-1.5 text-[15px] leading-relaxed text-ink-muted">
            See which learners need support, and what to teach them next.
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
              label="Password"
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {(error || (googleReason && GOOGLE_REASONS[googleReason])) && (
            <div className="mt-5">
              <Note tone="error">{error ?? GOOGLE_REASONS[googleReason ?? ""]}</Note>
            </div>
          )}

          <Button type="submit" disabled={busy} className="mt-7 w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>

          <GoogleButton />
        </form>

        <p className="mt-6 text-center text-[15px] text-ink-muted">
          Have a setup code from your head teacher?{" "}
          <Link href="/setup" className="font-medium text-ink underline underline-offset-2">
            Set up your account
          </Link>
        </p>

        <p className="mt-8 text-center text-sm text-ink-subtle">
          Kenya CBE · Grades 1–6
        </p>
      </div>
    </main>
  );
}
