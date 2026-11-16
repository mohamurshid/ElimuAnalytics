"use client";

/**
 * A learner's levels from observed tasks, newest first, grouped by task.
 *
 * On the learner page below the quiz levels, as its own kind of evidence:
 * the teacher's rubric judgement of what the learner did, beside the
 * estimate from what they answered. A report generated for a sub-strand
 * carries these levels and notes too, so the two can be read together.
 */

import { useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { LevelChip } from "@/components/Level";
import { KIND_LABEL } from "@/components/ObservedTasks";
import { Card, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { LearnerObservation } from "@/lib/types";

type Group = { head: LearnerObservation; rows: LearnerObservation[] };

function byTask(rows: LearnerObservation[]): Group[] {
  const groups: Group[] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last.head.task_id === row.task_id) last.rows.push(row);
    else groups.push({ head: row, rows: [row] });
  }
  return groups;
}

export function ObservedLevels({ studentId }: { studentId: string }) {
  const [rows, setRows] = useState<LearnerObservation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<LearnerObservation[]>(`/api/students/${studentId}/observations`)
      .then((next) => !cancelled && setRows(next))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load observed levels")));
    return () => {
      cancelled = true;
    };
  }, [studentId]);

  if (error) return <Note tone="error">{error}</Note>;
  if (!rows || rows.length === 0) return null;

  return (
    <section aria-labelledby="observed-heading" className="mt-8">
      <h2 id="observed-heading" className="mb-1 flex items-center gap-2.5 text-lg font-semibold text-ink">
        <Icon name="eye" className="size-5 text-brand-strong" />
        Observed in class
      </h2>
      <p className="mb-3 text-sm text-ink-muted">
        Levels the teacher gave from watching tasks, judged on the KICD rubric. A report
        for the same sub-strand includes them.
      </p>
      <ul className="space-y-3">
        {byTask(rows).map(({ head, rows: levels }) => {
          const [strand, sub] = head.strand.split(" / ");
          return (
            <li key={head.task_id}>
              <Card className="p-4">
                <p className="text-[15px] font-semibold text-ink">{head.title}</p>
                <p className="text-sm text-ink-subtle">
                  {KIND_LABEL[head.kind]} · {sub ?? strand}
                  {head.observed_at &&
                    ` · ${new Date(head.observed_at).toLocaleDateString(undefined, {
                      day: "numeric",
                      month: "short",
                    })}`}
                </p>
                <ul className="mt-3 space-y-3">
                  {levels.map((r, n) => (
                    <li key={n} className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between">
                      <span className="min-w-0 text-[15px] text-ink">
                        {r.indicator}
                        {r.note && <span className="mt-0.5 block text-sm text-ink-muted">{r.note}</span>}
                      </span>
                      <span className="shrink-0">
                        <LevelChip tier={r.tier} size="sm" />
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
