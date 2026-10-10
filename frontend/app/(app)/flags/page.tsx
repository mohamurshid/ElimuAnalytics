"use client";

/**
 * The intervention queue.
 *
 * Every row here survived two filters that matter more than the list itself:
 * the learner had a confident estimate, and it fell below threshold on two
 * consecutive assessments. A learner with too little evidence can never
 * appear, however poorly they seem to be doing — which is the point, and is
 * said on the page so nobody reads an empty queue as nothing being wrong.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Empty, Loading, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Flag } from "@/lib/types";

export default function FlagsPage() {
  const [rows, setRows] = useState<Flag[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchFlags = useCallback(() => api.get<Flag[]>("/api/flags"), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await fetchFlags();
        if (!cancelled) {
          setRows(next);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(errorMessage(e, "Could not load the queue"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchFlags]);

  return (
    <>
      <h1 className="text-2xl font-semibold">Intervention queue</h1>
      <p className="mt-1 max-w-3xl text-sm text-neutral-600">
        Learners flagged after <strong>two consecutive</strong> below-threshold
        assessments in the same strand. One weak result is not enough: a single
        bad day should not put a child into an intervention queue.
      </p>

      <div className="mt-4">
        <Note tone="error">{error}</Note>
      </div>

      {!rows && !error && (
        <div className="mt-6">
          <Loading what="the queue" />
        </div>
      )}

      {rows && rows.length === 0 && (
        <div className="mt-6">
          <Empty>
            Nobody is flagged. A flag needs two consecutive below-threshold
            assessments, so an empty queue early in a term is expected rather
            than reassuring.
          </Empty>
        </div>
      )}

      {rows && rows.length > 0 && (
        <table className="mt-6 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-neutral-300 text-left">
              <th className="py-2 pr-4 font-medium">Learner</th>
              <th className="py-2 pr-4 font-medium">Strand</th>
              <th className="py-2 pr-4 font-medium">Severity</th>
              <th className="py-2 font-medium">Flagged</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((flag) => (
              <tr key={flag.flag_id} className="border-b border-neutral-200">
                <td className="py-2 pr-4">
                  <Link
                    href={`/students/${flag.student_id}`}
                    className="underline underline-offset-2
                               hover:text-neutral-500"
                  >
                    {flag.learner}
                  </Link>
                </td>
                <td className="py-2 pr-4">{flag.strand}</td>
                <td className="py-2 pr-4">{flag.severity}</td>
                <td className="py-2 text-neutral-600">
                  {flag.flagged_at
                    ? new Date(flag.flagged_at).toLocaleDateString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
