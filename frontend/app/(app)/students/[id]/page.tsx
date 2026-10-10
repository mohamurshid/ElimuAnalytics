"use client";

/**
 * One learner, every strand.
 *
 * The page a teacher opens before acting on a flag, so it has to carry the
 * reasoning and not just the verdict: how many items the estimate rests on,
 * whether it is firm enough to act on, and — when there is no estimate — the
 * server's own sentence explaining why not.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Legend } from "@/components/Heatmap";
import { Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { shortTier, tierColour } from "@/lib/tiers";
import type { LearnerDiagnostics } from "@/lib/types";

const MINIMUM = 5;

export default function LearnerPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<LearnerDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchLearner = useCallback(
    () => api.get<LearnerDiagnostics>(`/api/students/${id}/diagnostics`),
    [id],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await fetchLearner();
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "No such learner at your school."
            : errorMessage(e, "Could not load this learner"),
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchLearner]);

  return (
    <>
      <h1 className="text-2xl font-semibold">{data?.name ?? "Learner"}</h1>
      {data && !data.is_active && (
        <p className="mt-1 text-sm text-neutral-500">
          Withdrawn. Past responses are kept, and this learner is excluded from
          future calibration.
        </p>
      )}

      <div className="mt-4">
        <Note tone="error">{error}</Note>
      </div>

      {!data && !error && (
        <div className="mt-6">
          <Loading what="diagnostics" />
        </div>
      )}

      {data && data.cells.length === 0 && (
        <div className="mt-6">
          <Empty>No strands have been assessed for this learner yet.</Empty>
        </div>
      )}

      {data && data.cells.length > 0 && (
        <>
          <div className="mt-6">
            <Legend minimum={MINIMUM} />
          </div>

          <ul className="mt-4 space-y-3">
            {data.cells.map((cell) => (
              <li
                key={cell.strand_id}
                className="tier-cell rounded-r px-4 py-3"
                style={{ ["--tier" as string]: tierColour(cell.tier) }}
              >
                <div className="flex flex-wrap items-baseline justify-between
                                gap-2">
                  <span className="font-medium">{cell.strand}</span>
                  <span className="text-sm">
                    {cell.theta === null ? (
                      <span className="text-neutral-600">no estimate</span>
                    ) : (
                      <>
                        <span className="font-medium">
                          {shortTier(cell.tier)}
                        </span>
                        <span className="text-neutral-600">
                          {" "}
                          · θ {cell.theta.toFixed(2)}
                        </span>
                      </>
                    )}
                  </span>
                </div>
                {/* The server's own words. Paraphrasing a refusal is how a
                    refusal turns into an apparent fault. */}
                <p className="mt-1 text-sm text-neutral-600">{cell.message}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}
