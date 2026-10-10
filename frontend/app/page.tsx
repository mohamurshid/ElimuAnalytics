"use client";

/**
 * The entry point decides where to send you, once it knows who you are.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

export default function Home() {
  const { profile, resolved } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!resolved) return;
    router.replace(profile ? "/dashboard" : "/login");
  }, [resolved, profile, router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-neutral-500">Loading…</p>
    </main>
  );
}
