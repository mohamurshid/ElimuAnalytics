"use client";

/**
 * Overview: the teacher's classes at a glance.
 *
 * Built only from data that exists. In particular there is no "progress over
 * time" chart: levels are stored per learner per strand, but nothing exposes
 * their history yet and with at most one recording there is nothing to plot.
 * An empty trend line would be decoration, and the brief for this page was
 * explicit about charts that exist to fill space.
 *
 * Each class's levels load independently. The heatmap endpoint takes several
 * seconds, so one slow or failing class must not hold the others back - every
 * card renders straight away with its name and count, and its bar arrives
 * when it arrives.
 *
 * **Waiting for review** (24 October): drafts for any teacher, and for a
 * head teacher the reported questions too. A report takes a question out of
 * quizzes and levels until a head teacher decides, and before this the only
 * sign of one was a badge on that strand's own page - a page a head teacher
 * has no reason to open.
 *
 * This page replaced a Stage 1 placeholder whose only job was to prove the
 * sign-in chain worked; its explanation of the refresh cookie was written for
 * whoever was testing it, not for a teacher.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { ClassSummary } from "@/components/Heatmap";
import { Icon } from "@/components/Icon";
import { Badge, ButtonLink, Card, Empty, IconTile, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { greeting } from "@/lib/people";
import { HOME } from "@/lib/routes";
import type { Classroom, Flag, Heatmap as HeatmapData, Strand } from "@/lib/types";

type Loadable<T> = { data: T } | { error: string } | null;

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

function ClassCard({ classroom }: { classroom: Classroom }) {
  const [levels, setLevels] = useState<Loadable<HeatmapData>>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<HeatmapData>(`/api/classrooms/${classroom.class_id}/heatmap`)
      .then((data) => !cancelled && setLevels({ data }))
      .catch((e) => !cancelled && setLevels({ error: errorMessage(e, "Could not load levels") }));
    return () => {
      cancelled = true;
    };
  }, [classroom.class_id]);

  const title = `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`;

  return (
    <Card className="overflow-hidden">
      <Link
        href={`/classrooms/${classroom.class_id}`}
        className="group flex min-h-16 items-center gap-3 border-b border-line px-4 py-3.5 hover:bg-sunken"
      >
        <IconTile name="classes" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-semibold text-ink">{title}</span>
          <span className="block text-sm text-ink-muted">
            {plural(classroom.student_count, "learner", "learners")}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1 text-sm font-semibold text-brand-strong">
          Open
          <Icon name="chevronRight" className="size-4 transition-transform group-hover:translate-x-0.5" />
        </span>
      </Link>
      <div className="p-4">
        {levels === null && <Loading what="levels" />}
        {levels && "error" in levels && <Note tone="error">{levels.error}</Note>}
        {levels && "data" in levels &&
          (levels.data.learners.length === 0 ? (
            <p className="text-[15px] text-ink-muted">No learners in this class yet.</p>
          ) : levels.data.strands.length === 0 ? (
            <p className="text-[15px] text-ink-muted">No strands are assessed yet.</p>
          ) : (
            <ClassSummary data={levels.data} />
          ))}
      </div>
    </Card>
  );
}

/**
 * Questions waiting on someone, with a way to each. Hidden when nothing is.
 * Drafts wait on any teacher; reported questions only on a head teacher,
 * who alone can keep, edit or retire one.
 */
function Waiting({ strands, isHead }: { strands: Strand[]; isHead: boolean }) {
  const reported = isHead ? strands.filter((s) => s.reported_items > 0 && s.class_id) : [];
  const drafts = strands.filter((s) => s.draft_items > 0 && s.class_id);
  const reportedCount = reported.reduce((n, s) => n + s.reported_items, 0);
  const draftCount = drafts.reduce((n, s) => n + s.draft_items, 0);
  if (reportedCount === 0 && draftCount === 0) return null;

  const name = (s: Strand) => {
    const [strand, sub] = s.name.split(" / ");
    return sub ?? strand;
  };

  return (
    <section aria-labelledby="waiting-heading">
      <h2 id="waiting-heading" className="mb-3 flex items-center gap-2.5 text-lg font-semibold text-ink">
        <IconTile name="sparkles" tone="accent" size="sm" />
        Waiting for review
      </h2>
      <Card className="overflow-hidden">
        {reportedCount > 0 && (
          <div className="border-b border-line px-4 py-4 last:border-b-0">
            <p className="text-[15px] font-semibold text-ink">
              {plural(reportedCount, "reported question", "reported questions")}
            </p>
            <p className="mt-0.5 text-sm text-ink-muted">
              Out of quizzes and levels until you keep, edit or retire{" "}
              {reportedCount === 1 ? "it" : "them"}.
            </p>
            <ul className="mt-2 space-y-1">
              {reported.map((s) => (
                <li key={s.strand_id}>
                  <Link
                    href={`/classrooms/${s.class_id}/strands/${s.strand_id}`}
                    className="flex min-h-11 items-center justify-between gap-3 rounded-xl
                               px-3 hover:bg-sunken"
                  >
                    <span className="min-w-0 truncate text-[15px] text-ink">{name(s)}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Badge tone="risk">{s.reported_items}</Badge>
                      <Icon name="chevronRight" className="size-4 text-ink-subtle" />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
        {draftCount > 0 && (
          <div className="px-4 py-4">
            <p className="text-[15px] font-semibold text-ink">
              {plural(draftCount, "AI-written question", "AI-written questions")} to review
            </p>
            <p className="mt-0.5 text-sm text-ink-muted">
              None is given to learners until a teacher approves it.
            </p>
            <ul className="mt-2 space-y-1">
              {drafts.map((s) => (
                <li key={s.strand_id}>
                  <Link
                    href={`/classrooms/${s.class_id}/strands/${s.strand_id}/review`}
                    className="flex min-h-11 items-center justify-between gap-3 rounded-xl
                               px-3 hover:bg-sunken"
                  >
                    <span className="min-w-0 truncate text-[15px] text-ink">{name(s)}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Badge tone="warn">{s.draft_items}</Badge>
                      <Icon name="chevronRight" className="size-4 text-ink-subtle" />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </section>
  );
}

export default function OverviewPage() {
  const { profile } = useAuth();
  const [flags, setFlags] = useState<Loadable<Flag[]>>(null);
  const [classes, setClasses] = useState<Loadable<Classroom[]>>(null);
  const [strands, setStrands] = useState<Loadable<Strand[]>>(null);

  useEffect(() => {
    let cancelled = false;
    // Settled separately: the support count failing should not blank the
    // classes, and the reverse.
    api
      .get<Flag[]>("/api/flags")
      .then((data) => !cancelled && setFlags({ data }))
      .catch((e) => !cancelled && setFlags({ error: errorMessage(e, "Could not load support list") }));
    api
      .get<Classroom[]>("/api/classrooms")
      .then((data) => !cancelled && setClasses({ data }))
      .catch((e) => !cancelled && setClasses({ error: errorMessage(e, "Could not load classes") }));
    api
      .get<Strand[]>("/api/strands")
      .then((data) => !cancelled && setStrands({ data }))
      .catch((e) => !cancelled && setStrands({ error: errorMessage(e, "Could not load questions") }));
    return () => {
      cancelled = true;
    };
  }, []);

  const isHead = profile ? profile.role !== "teacher" : false;
  const strandList = strands && "data" in strands ? strands.data : [];
  const supportCount = flags && "data" in flags ? flags.data.length : null;
  const classList = classes && "data" in classes ? classes.data.filter((c) => c.is_active) : null;
  const firstName = profile?.name?.split(" ")[0];

  return (
    <>
      <PageHeader
        eyebrow={firstName ? `${greeting()}, ${firstName}` : greeting()}
        title="Overview"
        description="Your classes at a glance."
      />

      <div className="space-y-8">
        {/* The one number on this page a teacher acts on. */}
        <Link
          href={HOME}
          className="group relative flex min-h-28 items-center justify-between gap-4 overflow-hidden
                     rounded-3xl bg-action px-5 py-5 text-action-ink shadow-lift transition-transform
                     hover:-translate-y-0.5 sm:px-7"
        >
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -right-10 -top-12 size-44 rounded-full bg-white/10"
          />
          <span className="relative flex items-center gap-4">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-white/15">
              <Icon name="support" className="size-6" />
            </span>
            <span>
              <span className="block text-sm font-semibold opacity-85">Need support</span>
              <span className="mt-0.5 block text-[17px] font-semibold">
                {supportCount === null
                  ? flags && "error" in flags
                    ? flags.error
                    : "Checking…"
                  : supportCount === 0
                    ? "No one yet"
                    : `${plural(supportCount, "learner", "learners")} to look at`}
              </span>
            </span>
          </span>
          <span className="relative flex items-center gap-2">
            {supportCount !== null && (
              <span className="text-4xl font-bold tabular-nums">{supportCount}</span>
            )}
            <Icon name="chevronRight" className="size-6 transition-transform group-hover:translate-x-0.5" />
          </span>
        </Link>

        <Waiting strands={strandList} isHead={isHead} />

        <section aria-labelledby="classes-heading">
          <h2 id="classes-heading" className="mb-3 flex items-center gap-2.5 text-lg font-semibold text-ink">
            <IconTile name="classes" size="sm" />
            Your classes
          </h2>
          {classes === null && <Loading what="classes" />}
          {classes && "error" in classes && <Note tone="error">{classes.error}</Note>}
          {classList && classList.length === 0 && (
            <Empty
              icon="classes"
              title="No classes yet"
              action={<ButtonLink href="/classrooms" variant="primary">Go to Classes</ButtonLink>}
            >
              Create a class and add your learners to see how they’re doing here.
            </Empty>
          )}
          {classList && classList.length > 0 && (
            <div className="grid gap-4 md:grid-cols-2">
              {classList.map((c) => (
                <ClassCard key={c.class_id} classroom={c} />
              ))}
            </div>
          )}
        </section>

        <section aria-labelledby="questions-heading">
          <h2 id="questions-heading" className="flex items-center gap-2.5 text-lg font-semibold text-ink">
            <IconTile name="book" size="sm" />
            Questions
          </h2>
          <p className="mb-3 mt-1 text-sm text-ink-muted">
            The strands your classes are quizzed on. A strand’s questions are
            calibrated once enough learners have answered them — use
            Recalibrate on a class page.
          </p>
          {strands === null && <Loading what="questions" />}
          {strands && "error" in strands && <Note tone="error">{strands.error}</Note>}
          {strands && "data" in strands && strands.data.length === 0 && (
            <Empty icon="book">No strands have questions yet.</Empty>
          )}
          {strands && "data" in strands && strands.data.length > 0 && (
            <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface shadow-soft">
              {strands.data.map((s) => {
                const [strandName, sub] = s.name.split(" / ");
                const calibrated = s.calibrated_items > 0;
                const body = (
                  <>
                    <span className="min-w-0">
                      <span className="block font-semibold text-ink">{sub ?? strandName}</span>
                      <span className="block text-sm text-ink-muted">
                        {sub ? `${strandName} · ` : ""}
                        {plural(s.active_items, "question", "questions")}
                      </span>
                    </span>
                    {/* Calibration and review are system state, so the semantic
                        colours apply here - they never touch a learner. */}
                    <span className="flex flex-wrap gap-1.5">
                      {isHead && s.reported_items > 0 && (
                        <Badge tone="risk">{s.reported_items} reported</Badge>
                      )}
                      {s.draft_items > 0 && <Badge tone="warn">{s.draft_items} to review</Badge>}
                      {calibrated ? (
                        <Badge tone="ok">{s.calibrated_items} calibrated</Badge>
                      ) : (
                        <Badge tone="warn">Not calibrated</Badge>
                      )}
                    </span>
                  </>
                );
                const row =
                  "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3.5";
                return (
                  <li key={s.strand_id}>
                    {s.class_id ? (
                      <Link
                        href={`/classrooms/${s.class_id}/strands/${s.strand_id}`}
                        className={`${row} min-h-14 hover:bg-sunken`}
                      >
                        {body}
                      </Link>
                    ) : (
                      <div className={row}>{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
