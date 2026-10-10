"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { profile, resolved, signIn } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in - a reload landed here, or the back button did.
  useEffect(() => {
    if (resolved && profile) router.replace("/dashboard");
  }, [resolved, profile, router]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(email, password);
      router.replace("/dashboard");
    } catch (e) {
      // 429 is the login throttle, and says when to come back. Showing the
      // server's own message avoids inventing a second vocabulary for it.
      setError(
        e instanceof ApiError ? e.message : "Could not reach the server.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-neutral-200
                   bg-white p-6 shadow-sm"
      >
        <h1 className="text-xl font-semibold">Elimu Analytics</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Sign in to your school account.
        </p>

        <label className="mt-6 block text-sm font-medium" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded border border-neutral-300 px-3 py-2
                     text-sm focus:border-neutral-900 focus:outline-none"
        />

        <label className="mt-4 block text-sm font-medium" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded border border-neutral-300 px-3 py-2
                     text-sm focus:border-neutral-900 focus:outline-none"
        />

        {error && (
          <p
            role="alert"
            className="mt-4 rounded border border-red-200 bg-red-50 px-3 py-2
                       text-sm text-red-800"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 w-full rounded bg-neutral-900 px-3 py-2 text-sm
                     font-medium text-white hover:bg-neutral-800
                     disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
