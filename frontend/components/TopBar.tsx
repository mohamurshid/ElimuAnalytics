"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";

export function TopBar() {
  const { profile, signOut } = useAuth();
  const router = useRouter();

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  return (
    <header className="border-b border-neutral-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <span className="font-semibold">Elimu Analytics</span>
        <div className="flex items-center gap-4 text-sm">
          <span className="text-neutral-600">
            {profile?.name}{" "}
            <span className="text-neutral-400">({profile?.role})</span>
          </span>
          <button
            onClick={handleSignOut}
            className="rounded border border-neutral-300 px-3 py-1
                       hover:bg-neutral-100"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
