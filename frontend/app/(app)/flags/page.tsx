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

import { Icon } from "@/components/Icon";
import { LevelAvatar, LevelChip } from "@/components/Level";
import { ButtonLink, Card, Empty, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { greeting } from "@/lib/people";
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
  const { profile } = useAuth();
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

  const firstName = profile?.name?.split(" ")[0];
  const below = rows?.filter((r) => r.severity === "Below expectation").length ?? 0;
  const approaches = rows?.filter((r) => r.severity === "Approaches expectation").length ?? 0;

  return (
    <>
      <PageHeader
        eyebrow={firstName ? `${greeting()}, ${firstName}` : greeting()}
        title="Learners to support"
        description="Learners who were below expectation in two assessments in a row. One weak result on its own isn’t enough to appear here."
      />

      <Note tone="error">{error}</Note>

      {!rows && !error && <Loading what="learners" />}

      {rows && rows.length === 0 && (
        <Empty
          icon="seedling"
          title="No one needs support yet"
          action={
            <ButtonLink href="/classrooms" variant="primary">
              <Icon name="classes" />
              Go to your classes
            </ButtonLink>
          }
        >
          Give a class a quiz, then record their levels. A learner appears here
          after two low results in a row on the same strand.
        </Empty>
      )}

      {rows && rows.length === 0 && (
        <ol className="mt-4 grid gap-3 sm:grid-cols-3">
          {[
            { icon: "paper" as const, title: "Give a quiz", body: "On a phone, or on paper you mark." },
            { icon: "save" as const, title: "Record levels", body: "From the class page, after each quiz." },
            { icon: "support" as const, title: "See who needs help", body: "Two low results in a row bring a learner here." },
          ].map((step, i) => (
            <li key={step.title}>
              <Card className="flex h-full items-start gap-3 p-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-fill text-brand-strong">
                  <Icon name={step.icon} />
                </span>
                <span>
                  <span className="block text-xs font-semibold text-ink-subtle">Step {i + 1}</span>
                  <span className="block text-[15px] font-semibold text-ink">{step.title}</span>
                  <span className="mt-0.5 block text-sm text-ink-muted">{step.body}</span>
                </span>
              </Card>
            </li>
          ))}
        </ol>
      )}

      {rows && rows.length > 0 && (
        <>
          <dl className="mb-5 grid grid-cols-3 gap-3">
            {[
              { label: "Need support", n: rows.length, tone: "bg-brand-fill text-brand-strong" },
              { label: "Below", n: below, tone: "bg-sunken text-ink" },
              { label: "Approaches", n: approaches, tone: "bg-sunken text-ink" },
            ].map((stat) => (
              <div key={stat.label} className={`rounded-2xl px-4 py-3 ${stat.tone}`}>
                <dt className="text-xs font-semibold opacity-80">{stat.label}</dt>
                <dd className="mt-0.5 text-2xl font-bold tabular-nums">{stat.n}</dd>
              </div>
            ))}
          </dl>
          <ul className="space-y-2.5">
            {rows.map((flag) => {
              const { strand, sub } = splitStrand(flag.strand);
              return (
                <li key={flag.flag_id}>
                  <Link
                    href={`/students/${flag.student_id}`}
                    className="flex min-h-20 items-center gap-3.5 rounded-2xl border border-line bg-surface px-4 py-3 shadow-soft transition-all hover:-translate-y-0.5 hover:shadow-lift"
                  >
                    {/* Severity is the learner's KICD level when flagged, so
                        it separates Approaches from Below - the triage a
                        teacher needs - in colour and, on the chip, in words. */}
                    <LevelAvatar name={flag.learner} tier={flag.severity} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-base font-semibold text-ink">
                        {flag.learner}
                      </span>
                      <span className="mt-0.5 block truncate text-sm text-ink-muted">
                        {sub}
                        {strand && <span className="text-ink-subtle"> · {strand}</span>}
                      </span>
                      <span className="mt-1.5 flex items-center gap-2">
                        <LevelChip tier={flag.severity} size="sm" />
                        {flag.flagged_at && (
                          <span className="text-xs text-ink-subtle">since {flaggedOn(flag.flagged_at)}</span>
                        )}
                      </span>
                    </span>
                    <Icon name="chevronRight" className="size-5 shrink-0 text-ink-subtle" />
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
