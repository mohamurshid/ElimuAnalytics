"use client";

/**
 * The entry point decides where to send you, once it knows who you are.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { HOME } from "@/lib/routes";

export default function Home() {
  const { profile, resolved } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!resolved) return;
    router.replace(profile ? HOME : "/login");
  }, [resolved, profile, router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="text-[15px] text-ink-muted">Loading…</p>
    </main>
  );
}
