"use client";

/**
 * Keeps a page from rendering to someone who is not signed in.
 *
 * It waits for `resolved` before deciding anything. Redirecting while the
 * answer is still unknown would bounce every valid session to the login page
 * for a moment on each reload - the bug this component exists to avoid.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

export function Guard({ children }: { children: React.ReactNode }) {
  const { profile, resolved } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (resolved && !profile) router.replace("/login");
  }, [resolved, profile, router]);

  if (!resolved) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-neutral-500">Restoring your session…</p>
      </main>
    );
  }

  if (!profile) return null; // redirecting

  return <>{children}</>;
}
