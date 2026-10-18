"use client";

/**
 * Learners to support - the home screen.
 *
 * Every row here survived two filters that matter more than the list itself:
 * the learner had a confident estimate, and it fell below threshold on two
 * consecutive assessments. A learner with too little evidence can never
 * appear, however poorly they seem to be doing. That rationale belongs here,
 * in the code; on the screen a teacher needs the plain version and a next
 * step.
 *
 * The empty state matters more than the list. Nobody is flagged until a class
 * has had two assessments, so every teacher's first sight of the app is this
 * page with nothing in it - which is why it points at the classes rather than
 * explaining the statistics.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ButtonLink, Empty, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { shortTier, tierColour } from "@/lib/tiers";
import type { Flag } from "@/lib/types";

/** "3.0 Force and Energy / 3.3 Heat Transfer" -> the sub-strand leads. */
function splitStrand(name: string): { strand: string; sub: string } {
  const [strand, sub] = name.split(" / ");
  return sub ? { strand, sub } : { strand: "", sub: name };
}

function flaggedOn(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

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
        if (!cancelled) setError(errorMessage(e, "Could not load this list"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchFlags]);

  return (
    <>
      <PageHeader
        title="Learners to support"
        description="Learners who were below expectation in two assessments in a row. One weak result on its own isn’t enough to appear here."
      />

      <Note tone="error">{error}</Note>

      {!rows && !error && <Loading what="learners" />}

      {rows && rows.length === 0 && (
        <Empty
          title="No one needs support yet"
          action={
            <ButtonLink href="/classrooms" variant="primary">
              Go to your classes
            </ButtonLink>
          }
        >
          Learners appear here after two assessments in a row below
          expectation. Give your class a quiz to get started.
        </Empty>
      )}

      {rows && rows.length > 0 && (
        <>
          <p className="mb-3 text-sm text-ink-subtle">
            {rows.length} {rows.length === 1 ? "learner" : "learners"}
          </p>
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {rows.map((flag) => {
              const { strand, sub } = splitStrand(flag.strand);
              return (
                <li key={flag.flag_id}>
                  <Link
                    href={`/students/${flag.student_id}`}
                    className="flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-sunken"
                  >
                    {/* Severity is the learner's KICD tier when flagged, so it
                        separates Approaches from Below - the triage a teacher
                        needs. The band carries it in colour and the subline in
                        words, because colour must never be the only signal. */}
                    <span
                      aria-hidden="true"
                      className="h-10 w-1 shrink-0 rounded-full"
                      style={{ background: tierColour(flag.severity) }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-base font-semibold text-ink">
                        {flag.learner}
                      </span>
                      <span className="block truncate text-sm text-ink-muted">
                        <span className="font-medium text-ink">{shortTier(flag.severity)}</span>
                        {" · "}
                        {sub}
                        {strand && <span className="text-ink-subtle"> · {strand}</span>}
                      </span>
                    </span>
                    <span className="shrink-0 text-right">
                      {flag.flagged_at && (
                        <span className="block text-xs text-ink-subtle">
                          {flaggedOn(flag.flagged_at)}
                        </span>
                      )}
                      <span aria-hidden="true" className="text-xl leading-none text-ink-subtle">
                        ›
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </>
  );
}
