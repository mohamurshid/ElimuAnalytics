"use client";

/**
 * A class's observed tasks: what was watched, on which sub-strand, and how
 * many learners reached each KICD level.
 *
 * Shown under the heatmap, not in it. The heatmap's cells are estimates from
 * answers; these are a teacher's rubric judgements. Drawn side by side, a
 * teacher can see where the two agree and where they do not - which is the
 * point of having both.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { LevelChip } from "@/components/Level";
import { ButtonLink, Card, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { tierColour, TIERS } from "@/lib/tiers";
import type { ObservationSummary, TaskKind } from "@/lib/types";

export const KIND_LABEL: Record<TaskKind, string> = {
  observation: "Observation",
  project: "Project",
  presentation: "Presentation",
};

function subStrand(name: string): string {
  const [strand, sub] = name.split(" / ");
  return sub ?? strand;
}

export function ObservedTasks({ classId }: { classId: string }) {
  const [rows, setRows] = useState<ObservationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<ObservationSummary[]>(`/api/classrooms/${classId}/observations`)
      .then((next) => !cancelled && setRows(next))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load observed tasks")));
    return () => {
      cancelled = true;
    };
  }, [classId]);

  if (error) return <Note tone="error">{error}</Note>;
  if (!rows) return null;

  return (
    <section aria-labelledby="observed-heading">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="observed-heading" className="text-lg font-semibold text-ink">
          Observed tasks
        </h2>
        <ButtonLink href={`/classrooms/${classId}/observe`} size="sm">
          <Icon name="eye" className="size-4" /> Observe a task
        </ButtonLink>
      </div>
      {rows.length === 0 ? (
        <Card className="p-4">
          <p className="text-[15px] text-ink-muted">
            Nothing observed yet. Not everything a learner can do shows up in a quiz: a
            practical, a project or a presentation can be judged here against the KICD
            rubric, and appears beside the quiz levels.
          </p>
        </Card>
      ) : (
        <ul className="space-y-2.5">
          {rows.map((task) => {
            const total = task.learners_observed;
            return (
              <li key={task.task_id}>
                <Link
                  href={`/classrooms/${classId}/observe?task=${task.task_id}`}
                  className="block rounded-2xl border border-line bg-surface p-4 shadow-soft transition-all hover:-translate-y-0.5 hover:shadow-lift"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[15px] font-semibold text-ink">{task.title}</p>
                      <p className="mt-0.5 truncate text-sm text-ink-muted">
                        {KIND_LABEL[task.kind]} · {subStrand(task.strand)}
                        {task.created_at &&
                          ` · ${new Date(task.created_at).toLocaleDateString(undefined, {
                            day: "numeric",
                            month: "short",
                          })}`}
                      </p>
                    </div>
                    <Icon name="chevronRight" className="size-5 shrink-0 text-ink-subtle" />
                  </div>
                  {total === 0 ? (
                    <p className="mt-2 text-sm text-ink-subtle">No learners given a level yet.</p>
                  ) : (
                    <>
                      <div
                        aria-hidden="true"
                        className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-sunken"
                      >
                        {TIERS.map((tier) =>
                          task.levels[tier] ? (
                            <span
                              key={tier}
                              style={{
                                width: `${(100 * task.levels[tier]) / total}%`,
                                background: tierColour(tier),
                              }}
                            />
                          ) : null,
                        )}
                      </div>
                      <p className="mt-2 flex flex-wrap gap-1.5">
                        {TIERS.filter((tier) => task.levels[tier]).map((tier) => (
                          <LevelChip
                            key={tier}
                            tier={tier}
                            size="sm"
                            label={`${task.levels[tier]} ${tier.replace(/ expectation$/, "")}`}
                          />
                        ))}
                      </p>
                    </>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
