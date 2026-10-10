"use client";

/**
 * Stage 1 placeholder. It exists to prove the chain end to end: sign in,
 * reach a protected page, call an authenticated endpoint with the in-memory
 * token, and survive a reload on the refresh cookie alone.
 *
 * Stages 2 and 3 replace the body with classrooms and the competency heatmap.
 */

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Strand } from "@/lib/types";

export default function DashboardPage() {
  const { profile } = useAuth();
  const [strands, setStrands] = useState<Strand[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Strand[]>("/api/strands")
      .then(setStrands)
      .catch((e) =>
        setError(e instanceof ApiError ? e.message : "Request failed"),
      );
  }, []);

  return (
    <>
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-1 text-sm text-neutral-600">
        Signed in as {profile?.email}. Reload this page — the access token is
        held in memory and dies with it, and the session is restored from the
        httpOnly refresh cookie before anything renders.
      </p>

      <section className="mt-8">
        <h2 className="text-sm font-medium uppercase tracking-wide
                       text-neutral-500">
          Strands
        </h2>

        {error && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {error}
          </p>
        )}

        {!strands && !error && (
          <p className="mt-3 text-sm text-neutral-500">Loading…</p>
        )}

        {strands && (
          <table className="mt-3 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-neutral-300 text-left">
                <th className="py-2 pr-4 font-medium">Strand</th>
                <th className="py-2 pr-4 font-medium">Level</th>
                <th className="py-2 pr-4 font-medium">Active items</th>
                <th className="py-2 font-medium">Calibrated</th>
              </tr>
            </thead>
            <tbody>
              {strands.map((s) => (
                <tr key={s.strand_id} className="border-b border-neutral-200">
                  <td className="py-2 pr-4">{s.name}</td>
                  <td className="py-2 pr-4 text-neutral-600">{s.level}</td>
                  <td className="py-2 pr-4">{s.active_items}</td>
                  <td className="py-2">
                    {s.calibrated_items === 0 ? (
                      <span className="text-neutral-500">
                        not yet calibrated
                      </span>
                    ) : (
                      s.calibrated_items
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
