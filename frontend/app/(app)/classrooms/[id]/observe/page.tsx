"use client";

/**
 * Observing a task: learners judged against the KICD rubric, not marked
 * right or wrong.
 *
 * Added 16 November, after supervisor feedback that the system saw only
 * question answering. The KICD designs assess much of the curriculum by
 * watching learners do things - a practical, a project, a presentation - and
 * give each indicator four levels with a description of each. This page is
 * that rubric made usable on a phone.
 *
 * Built on the paper quiz's pattern, because a teacher already knows it:
 *
 *   - **The task is fixed first.** A sub-strand, a kind, a name, and one to
 *     five indicators chosen when it is made, as a quiz's questions are, so
 *     every learner is judged against the same thing. The KICD rubric rows
 *     for the sub-strand's grade and learning area are offered, those that
 *     share words with its name first. Most sub-strands have none, so a
 *     teacher can write one.
 *   - **One learner at a time,** full-size level buttons, Previous and Next.
 *     The chosen level's KICD description is shown under it, so the teacher
 *     judges against the curriculum's words rather than a feeling.
 *   - **Kept on the device as it is given** (lib/pending.ts) and saved with
 *     one button. Saving is idempotent - the same levels sent twice change
 *     nothing - so a save that drops can simply be sent again.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/Icon";
import { LevelChip } from "@/components/Level";
import { KIND_LABEL } from "@/components/ObservedTasks";
import { PendingCard } from "@/components/PendingCard";
import {
  Badge,
  Button,
  Card,
  Empty,
  Field,
  IconTile,
  Loading,
  Note,
  PageHeader,
  Segmented,
  Select,
} from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  clearPending,
  describePending,
  newBatchId,
  type PendingBatch,
  readPending,
  savePending,
  sendWithRetry,
} from "@/lib/pending";
import { initials } from "@/lib/people";
import { tierColour } from "@/lib/tiers";
import type {
  Classroom,
  Indicator,
  ObservationSummary,
  ObservationTask,
  RubricLevel,
  Strand,
  TaskKind,
} from "@/lib/types";

const LEVELS: { level: RubricLevel; tier: string; field: keyof Indicator }[] = [
  { level: 4, tier: "Exceeds expectation", field: "exceeds" },
  { level: 3, tier: "Meets expectation", field: "meets" },
  { level: 2, tier: "Approaches expectation", field: "approaches" },
  { level: 1, tier: "Below expectation", field: "below" },
];
const TIER_OF: Record<RubricLevel, string> = { 4: LEVELS[0].tier, 3: LEVELS[1].tier, 2: LEVELS[2].tier, 1: LEVELS[3].tier };
const MAX_INDICATORS = 5;

/** The same rounding the server uses for a learner's level on a task. */
function tierForMean(mean: number): string {
  if (mean >= 3.5) return TIER_OF[4];
  if (mean >= 2.5) return TIER_OF[3];
  if (mean >= 1.5) return TIER_OF[2];
  return TIER_OF[1];
}

type Entry = { level: RubricLevel | null; note: string };
type Grid = Record<string, Entry>; // "studentId:indicatorId"
type ScoreRow = {
  student_id: string;
  indicator_id: string;
  level: RubricLevel | null;
  note: string | null;
};

const key = (studentId: string, indicatorId: string) => `${studentId}:${indicatorId}`;

function gridFrom(task: ObservationTask): Grid {
  return Object.fromEntries(
    task.scores.map((s) => [key(s.student_id, s.indicator_id), { level: s.level, note: s.note ?? "" }]),
  );
}

function rowsFrom(grid: Grid, keys: Iterable<string>): ScoreRow[] {
  return [...keys].map((k) => {
    const [student_id, indicator_id] = k.split(":");
    const entry = grid[k] ?? { level: null, note: "" };
    return { student_id, indicator_id, level: entry.level, note: entry.note.trim() || null };
  });
}

function subStrand(name: string): string {
  const [strand, sub] = name.split(" / ");
  return sub ?? strand;
}

/** The task id in the address, so a task opened from the class page opens here. */
function taskInAddress(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("task") ?? "";
}

function showTaskInAddress(taskId: string) {
  const url = new URL(window.location.href);
  if (taskId) url.searchParams.set("task", taskId);
  else url.searchParams.delete("task");
  window.history.replaceState(null, "", url.toString());
}

export default function ObservePage() {
  const { id: classId } = useParams<{ id: string }>();
  const { profile } = useAuth();
  const teacherId = profile?.teacher_id;

  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [strands, setStrands] = useState<Strand[]>([]);
  const [tasks, setTasks] = useState<ObservationSummary[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // --- a new task ---
  const [strandId, setStrandId] = useState("");
  const [kind, setKind] = useState<TaskKind>("observation");
  const [title, setTitle] = useState("");
  const [offered, setOffered] = useState<Indicator[] | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [ownText, setOwnText] = useState("");

  // --- the open task ---
  const [taskId, setTaskId] = useState<string>(taskInAddress);
  const [task, setTask] = useState<ObservationTask | null>(null);
  const [grid, setGrid] = useState<Grid>({});
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [current, setCurrent] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string>(newBatchId);
  const [pending, setPending] = useState<PendingBatch<ScoreRow> | null>(() =>
    readPending<ScoreRow>("observe", classId, profile?.teacher_id),
  );

  /* --- the class, its strands and its tasks ---------------------------- */
  const loadTasks = useCallback(
    () => api.get<ObservationSummary[]>(`/api/classrooms/${classId}/observations`),
    [classId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [classes, classStrands, list] = await Promise.all([
          api.get<Classroom[]>("/api/classrooms"),
          api.get<Strand[]>(`/api/classrooms/${classId}/strands`),
          loadTasks(),
        ]);
        if (cancelled) return;
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
        setStrands(classStrands);
        setStrandId((s) => s || classStrands[0]?.strand_id || "");
        setTasks(list);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "No such classroom at your school."
            : errorMessage(e, "Could not load the class"),
        );
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [classId, loadTasks]);

  /* --- the indicators a new task on this strand may use ---------------- */
  useEffect(() => {
    if (!strandId || taskId) return;
    let cancelled = false;
    api
      .get<Indicator[]>(`/api/strands/${strandId}/indicators`)
      .then((rows) => !cancelled && setOffered(rows))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the indicators")));
    return () => {
      cancelled = true;
    };
  }, [strandId, taskId]);

  /* --- an open task, with any levels kept on this device restored ------- */
  useEffect(() => {
    showTaskInAddress(taskId);
    if (!taskId) return;
    let cancelled = false;
    api
      .get<ObservationTask>(`/api/observations/${taskId}`)
      .then((loaded) => {
        if (cancelled) return;
        const next = gridFrom(loaded);
        const kept = readPending<ScoreRow>("observe", classId, teacherId);
        setPending(kept);
        const restored = new Set<string>();
        if (kept && kept.taskId === loaded.task_id) {
          for (const r of kept.responses) {
            const k = key(r.student_id, r.indicator_id);
            next[k] = { level: r.level, note: r.note ?? "" };
            restored.add(k);
          }
          setBatchId(kept.batchId);
        }
        setTask(loaded);
        setGrid(next);
        setDirty(restored);
        setCurrent(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(errorMessage(e, "Could not open this task"));
        setTask(null);
        setTaskId("");
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, classId, teacherId]);

  /** Back to the list of tasks. State is reset here, in the handler, not in
   * an effect, so nothing renders a frame with the old task's grid. */
  function closeTask() {
    setTaskId("");
    setTask(null);
    setCurrent(null);
    setOffered(null);
    setChosen([]);
  }

  function chooseStrand(next: string) {
    setStrandId(next);
    setOffered(null);
    setChosen([]);
  }

  /* --- giving levels ----------------------------------------------------- */
  function keep(nextGrid: Grid, nextDirty: Set<string>) {
    // One set of unsaved levels is kept per class. Levels kept from another
    // task are saved or discarded first, never silently replaced by these.
    if (pending && pending.taskId !== task?.task_id) {
      setError("Save or discard the levels kept from the other task first.");
      return;
    }
    setGrid(nextGrid);
    setDirty(nextDirty);
    if (!task || !teacherId) return;
    const rows = rowsFrom(nextGrid, nextDirty);
    savePending<ScoreRow>({
      kind: "observe",
      teacherId,
      classId,
      strandId: task.strand_id,
      taskId: task.task_id,
      batchId,
      responses: rows,
      learners: new Set(rows.map((r) => r.student_id)).size,
    });
    if (pending) setPending(null);
  }

  function setEntry(studentId: string, indicatorId: string, change: Partial<Entry>) {
    const k = key(studentId, indicatorId);
    const entry = { ...(grid[k] ?? { level: null, note: "" }), ...change };
    keep({ ...grid, [k]: entry }, new Set(dirty).add(k));
  }

  async function save() {
    if (!task || dirty.size === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await sendWithRetry(() =>
        api.put<ObservationTask>(`/api/observations/${task.task_id}/scores`, {
          scores: rowsFrom(grid, dirty),
        }),
      );
      clearPending("observe", classId);
      setPending(null);
      setTask(saved);
      setGrid(gridFrom(saved));
      setDirty(new Set());
      setBatchId(newBatchId());
      const learners = new Set(saved.scores.map((s) => s.student_id)).size;
      setNotice(
        `Saved. ${learners} of ${saved.learners.length} learners have a level on this task.`,
      );
      setTasks(await loadTasks());
    } catch (e) {
      setError(
        `${errorMessage(e, "Could not save the levels")} They are kept on this device; ` +
          "save again when you are back online.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function savePendingNow() {
    if (!pending?.taskId) return;
    setBusy(true);
    setError(null);
    try {
      await sendWithRetry(() =>
        api.put(`/api/observations/${pending.taskId}/scores`, { scores: pending.responses }),
      );
      clearPending("observe", classId);
      setPending(null);
      setNotice("The levels kept on this device are saved.");
      setTasks(await loadTasks());
    } catch (e) {
      setError(errorMessage(e, "Could not save them"));
    } finally {
      setBusy(false);
    }
  }

  function discardPending() {
    clearPending("observe", classId);
    setPending(null);
  }

  /* --- making a task ------------------------------------------------------ */
  function toggle(indicatorId: string) {
    setChosen((now) =>
      now.includes(indicatorId)
        ? now.filter((i) => i !== indicatorId)
        : now.length >= MAX_INDICATORS
          ? now
          : [...now, indicatorId],
    );
  }

  async function writeOwn() {
    if (ownText.trim().length < 5) return;
    setBusy(true);
    setError(null);
    try {
      const made = await api.post<Indicator>(`/api/strands/${strandId}/indicators`, {
        indicator: ownText,
      });
      setOffered((rows) => [made, ...(rows ?? [])]);
      setChosen((now) => (now.length >= MAX_INDICATORS ? now : [...now, made.indicator_id]));
      setOwnText("");
    } catch (e) {
      setError(errorMessage(e, "Could not add the indicator"));
    } finally {
      setBusy(false);
    }
  }

  async function makeTask() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const made = await api.post<ObservationTask>(`/api/classrooms/${classId}/observations`, {
        strand_id: strandId,
        kind,
        title,
        indicator_ids: chosen,
      });
      setTitle("");
      setChosen([]);
      setTasks(await loadTasks());
      setTaskId(made.task_id);
    } catch (e) {
      setError(errorMessage(e, "Could not make the task"));
    } finally {
      setBusy(false);
    }
  }

  /* --- what the page shows ---------------------------------------------- */
  const classTitle = classroom
    ? `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`
    : "Class";
  const learners = task?.learners ?? [];
  const learner = learners.find((l) => l.student_id === current) ?? null;
  const at = learner ? learners.indexOf(learner) : -1;
  const pendingElsewhere = pending && pending.taskId !== task?.task_id ? pending : null;

  const progress = useMemo(() => {
    const out: Record<string, { given: number; tier: string | null }> = {};
    if (!task) return out;
    for (const l of task.learners) {
      const levels = task.indicators
        .map((i) => grid[key(l.student_id, i.indicator_id)]?.level)
        .filter((v): v is RubricLevel => !!v);
      out[l.student_id] = {
        given: levels.length,
        tier: levels.length ? tierForMean(levels.reduce((a, b) => a + b, 0) / levels.length) : null,
      };
    }
    return out;
  }, [task, grid]);

  const canMake = strandId && title.trim() && chosen.length > 0 && !busy;

  return (
    <>
      <PageHeader
        back={{ href: `/classrooms/${classId}`, label: classTitle }}
        eyebrow={classTitle}
        title={task ? task.title : "Observe a task"}
        description={
          task
            ? `${KIND_LABEL[task.kind]} · ${subStrand(task.strand)}. Give each learner the level that best describes what you saw.`
            : "A practical, project or presentation, judged against the KICD rubric rather than marked right or wrong."
        }
      />

      <div className="space-y-3">
        <Note tone="error">{error}</Note>
        <Note tone="ok">{notice}</Note>
        {pendingElsewhere && (
          <PendingCard
            description={describePending(pendingElsewhere, "levels, on another task,")}
            busy={busy}
            onSave={savePendingNow}
            onDiscard={discardPending}
          />
        )}
      </div>

      {!ready && <Loading what="the class" />}

      {ready && strands.length === 0 && !error && (
        <Note>
          This class isn’t assessed on any sub-strand yet. Add one on the class page first.
        </Note>
      )}

      {/* --- choosing or making a task ------------------------------------ */}
      {ready && !taskId && strands.length > 0 && (
        <div className="mt-4 space-y-6">
          {tasks.length > 0 && (
            <Card className="overflow-hidden">
              <h2 className="flex items-center gap-3 px-4 pt-4 text-lg font-semibold text-ink sm:px-6">
                <IconTile name="eye" />
                Carry on with a task
              </h2>
              <ul className="mt-3 divide-y divide-line border-t border-line">
                {tasks.map((t) => (
                  <li key={t.task_id}>
                    <button
                      type="button"
                      onClick={() => setTaskId(t.task_id)}
                      className="group flex min-h-16 w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-sunken sm:px-6"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-[15px] font-semibold text-ink">{t.title}</span>
                        <span className="block truncate text-sm text-ink-muted">
                          {KIND_LABEL[t.kind]} · {subStrand(t.strand)} · {t.learners_observed} observed
                        </span>
                      </span>
                      <Icon name="chevronRight" className="size-4 shrink-0 text-ink-subtle" />
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-4 sm:p-6">
            <h2 className="flex items-center gap-3 text-lg font-semibold text-ink">
              <IconTile name="plus" />
              A new task
            </h2>
            <div className="mt-4 space-y-4">
              <Select label="Sub-strand" value={strandId} onChange={(e) => chooseStrand(e.target.value)}>
                {strands.map((s) => (
                  <option key={s.strand_id} value={s.strand_id}>
                    {s.name}
                  </option>
                ))}
              </Select>

              <div>
                <span className="text-sm font-medium text-ink">What the class did</span>
                <div className="mt-1.5">
                  <Segmented
                    label="Kind of task"
                    value={kind}
                    onChange={setKind}
                    options={(Object.keys(KIND_LABEL) as TaskKind[]).map((k) => ({
                      value: k,
                      label: KIND_LABEL[k],
                    }))}
                  />
                </div>
              </div>

              <Field
                label="Name"
                name="title"
                value={title}
                maxLength={200}
                placeholder="e.g. Showing how heat moves through a metal spoon"
                onChange={(e) => setTitle(e.target.value)}
              />

              <fieldset>
                <legend className="text-sm font-medium text-ink">
                  Indicators to judge against{" "}
                  <span className="font-normal text-ink-subtle">
                    ({chosen.length} of up to {MAX_INDICATORS})
                  </span>
                </legend>
                {offered === null ? (
                  <p className="mt-2 text-sm text-ink-muted">Loading the rubric…</p>
                ) : offered.length === 0 ? (
                  <p className="mt-2 text-sm text-ink-muted">
                    The KICD design has no rubric for this sub-strand’s grade and learning area.
                    Write the indicator you will judge against below.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {offered.map((ind, n) => {
                      const on = chosen.includes(ind.indicator_id);
                      const firstOther = !ind.suggested && (n === 0 || offered[n - 1].suggested);
                      return (
                        <li key={ind.indicator_id}>
                          {firstOther && (
                            <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-ink-subtle">
                              Others for this grade and learning area
                            </p>
                          )}
                          <label
                            className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${
                              on ? "border-action bg-brand-fill" : "border-line hover:bg-sunken"
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="mt-1 size-4 accent-action"
                              checked={on}
                              disabled={!on && chosen.length >= MAX_INDICATORS}
                              onChange={() => toggle(ind.indicator_id)}
                            />
                            <span className="min-w-0 text-[15px] text-ink">
                              {ind.indicator}
                              <span className="ml-2 align-middle">
                                <Badge>{ind.source === "kicd" ? "KICD rubric" : "Written at your school"}</Badge>
                              </span>
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}

                <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                  <div className="min-w-0 flex-1">
                    <Field
                      label="Or write your own"
                      name="own-indicator"
                      value={ownText}
                      maxLength={300}
                      placeholder="e.g. Explains why a pot handle is made of wood"
                      onChange={(e) => setOwnText(e.target.value)}
                    />
                  </div>
                  <Button
                    variant="secondary"
                    disabled={busy || ownText.trim().length < 5 || chosen.length >= MAX_INDICATORS}
                    onClick={writeOwn}
                  >
                    Add
                  </Button>
                </div>
              </fieldset>

              <Button disabled={!canMake} onClick={makeTask}>
                {busy ? "Making…" : "Make the task"}
              </Button>
            </div>
          </Card>
        </div>
      )}

      {taskId && !task && !error && <Loading what="the task" />}

      {/* --- one learner --------------------------------------------------- */}
      {task && learner && (
        <section aria-labelledby="learner-heading" className="mt-6">
          <Button variant="ghost" className="-ml-3" onClick={() => setCurrent(null)}>
            <Icon name="chevronLeft" className="size-4" /> All learners
          </Button>
          <Card className="mt-2 p-4 sm:p-6">
            <div className="flex items-center gap-3">
              <span
                aria-hidden="true"
                className="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-fill text-sm font-bold text-brand-strong"
              >
                {initials(learner.name)}
              </span>
              <div className="min-w-0">
                <h2 id="learner-heading" className="text-lg font-semibold text-ink">
                  {learner.name}
                </h2>
                <p className="text-sm text-ink-muted">
                  {at + 1} of {learners.length} learners
                </p>
              </div>
            </div>

            <ol className="mt-4 divide-y divide-line">
              {task.indicators.map((ind) => {
                const entry = grid[key(learner.student_id, ind.indicator_id)] ?? { level: null, note: "" };
                const picked = LEVELS.find((l) => l.level === entry.level);
                const description = picked ? (ind[picked.field] as string | null) : null;
                return (
                  <li key={ind.indicator_id} className="py-4">
                    <p className="text-[15px] font-medium text-ink">{ind.indicator}</p>
                    <div
                      role="radiogroup"
                      aria-label={`${ind.indicator} for ${learner.name}`}
                      className="mt-2 grid grid-cols-2 gap-1 rounded-xl bg-sunken p-1 sm:grid-cols-4"
                    >
                      {LEVELS.map((l) => {
                        const on = entry.level === l.level;
                        return (
                          <button
                            key={l.level}
                            type="button"
                            role="radio"
                            aria-checked={on}
                            onClick={() =>
                              setEntry(learner.student_id, ind.indicator_id, { level: on ? null : l.level })
                            }
                            className={`flex min-h-11 items-center justify-center gap-2 rounded-lg text-[15px] font-semibold transition-all ${
                              on ? "text-ink shadow-soft" : "text-ink-muted hover:text-ink"
                            }`}
                            style={
                              on
                                ? { background: `color-mix(in oklab, ${tierColour(l.tier)} 28%, var(--surface))` }
                                : undefined
                            }
                          >
                            <span
                              aria-hidden="true"
                              className="size-2.5 shrink-0 rounded-full"
                              style={{ background: tierColour(l.tier) }}
                            />
                            {l.tier.replace(/ expectation$/, "")}
                          </button>
                        );
                      })}
                    </div>
                    <p className="mt-2 text-sm text-ink-muted">
                      {picked
                        ? description || `${picked.tier}.`
                        : "Choose the level that best describes what you saw. Tap it again to clear it."}
                    </p>
                    <div className="mt-2">
                      <Field
                        label="What you saw (optional)"
                        name={`note-${ind.indicator_id}`}
                        value={entry.note}
                        maxLength={500}
                        onChange={(e) =>
                          setEntry(learner.student_id, ind.indicator_id, { note: e.target.value })
                        }
                      />
                    </div>
                  </li>
                );
              })}
            </ol>

            <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
              <Button
                variant="secondary"
                disabled={at <= 0}
                onClick={() => setCurrent(learners[at - 1].student_id)}
              >
                <Icon name="chevronLeft" className="size-4" /> Previous
              </Button>
              <Button
                disabled={at >= learners.length - 1}
                onClick={() => {
                  setCurrent(learners[at + 1].student_id);
                  window.scrollTo({ top: 0 });
                }}
              >
                Next learner <Icon name="chevronRight" className="size-4" />
              </Button>
            </div>
          </Card>
        </section>
      )}

      {/* --- every learner ------------------------------------------------- */}
      {task && !learner && (
        <section aria-labelledby="learners-heading" className="mt-6">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 id="learners-heading" className="flex items-center gap-2.5 text-lg font-semibold text-ink">
              <IconTile name="users" size="sm" />
              Each learner
            </h2>
            <Button variant="ghost" size="sm" onClick={closeTask}>
              Another task
            </Button>
          </div>

          <Card className="mb-4 p-4">
            <p className="text-sm font-medium text-ink">Judged against</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[15px] text-ink-muted">
              {task.indicators.map((i) => (
                <li key={i.indicator_id}>{i.indicator}</li>
              ))}
            </ul>
          </Card>

          {learners.length === 0 ? (
            <Empty icon="users">
              No learners enrolled.{" "}
              <Link href={`/classrooms/${classId}/roll`} className="underline underline-offset-2">
                Enrol some on the roll
              </Link>
              .
            </Empty>
          ) : (
            <Card className="overflow-hidden">
              <ul className="divide-y divide-line">
                {learners.map((l) => {
                  const p = progress[l.student_id] ?? { given: 0, tier: null };
                  return (
                    <li key={l.student_id}>
                      <button
                        type="button"
                        onClick={() => {
                          setCurrent(l.student_id);
                          window.scrollTo({ top: 0 });
                        }}
                        className="group flex min-h-16 w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-sunken"
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span
                            aria-hidden="true"
                            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-bold text-ink-muted"
                          >
                            {initials(l.name)}
                          </span>
                          <span className="min-w-0 truncate text-[15px] font-semibold text-ink">{l.name}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2">
                          {p.tier ? (
                            <LevelChip tier={p.tier} size="sm" />
                          ) : (
                            <span className="text-sm text-ink-muted">Not observed</span>
                          )}
                          {p.given > 0 && p.given < task.indicators.length && (
                            <span className="text-xs text-ink-subtle">
                              {p.given}/{task.indicators.length}
                            </span>
                          )}
                          <Icon name="chevronRight" className="size-4 text-ink-subtle" />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </section>
      )}

      {/* Save stays in reach wherever the teacher is in the task. */}
      {task && (
        <div className="sticky bottom-[calc(5rem+env(safe-area-inset-bottom))] z-10 mt-6 flex md:bottom-3 flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface p-3 shadow-lift">
          <Button disabled={busy || dirty.size === 0} onClick={save}>
            <Icon name="save" className="size-4" />
            {busy ? "Saving…" : "Save levels"}
          </Button>
          <span className="text-sm text-ink-muted">
            {dirty.size === 0
              ? "Everything is saved."
              : `${dirty.size} ${dirty.size === 1 ? "change" : "changes"} not saved yet — kept on this device.`}
          </span>
        </div>
      )}
    </>
  );
}
