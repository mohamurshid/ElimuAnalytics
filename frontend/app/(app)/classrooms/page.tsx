"use client";

/**
 * The school's classes.
 *
 * Every row came back scoped: the API returns the caller's own school and
 * nothing else, so there is no school filter here and no way to ask for one.
 *
 * Creating, removing and restoring are school_admin actions. The controls are
 * hidden from a plain teacher rather than shown and rejected - but the hiding
 * is cosmetic, and the server enforces it either way. An interface that only
 * hides is not access control.
 *
 * Three presentation decisions:
 *
 * **Status appears only when it is the exception.** The old table had a
 * Status column reading "active" on every class anyone normally sees. Now an
 * active class shows no status; a withdrawn one says so, and Current and
 * Withdrawn are two views rather than one mixed list behind a checkbox.
 *
 * **Remove asks first.** It used to act on a single tap, from a button beside
 * every class on a phone. It is a two-step confirmation inline, not a pop-up.
 *
 * **The grade is chosen, not typed.** Report retrieval matches a class's grade
 * to the curriculum's by equality, so a typed "grade 5" made a class whose
 * reports could never find any curriculum. The server now refuses anything
 * but the six values too; the picker just stops the mistake earlier.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, Empty, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Classroom, Removal, Restore } from "@/lib/types";

const GRADES = ["Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6"];

function className(row: Classroom) {
  return `${row.grade}${row.name ? ` ${row.name}` : ""}`;
}

function learners(n: number) {
  return n === 0 ? "No learners yet" : `${n} ${n === 1 ? "learner" : "learners"}`;
}

/** "Grade 5" -> "5". Anything unexpected is shown whole rather than guessed at. */
function gradeNumber(grade: string) {
  return grade.match(/^Grade (\d)$/)?.[1] ?? grade;
}

export default function ClassesPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role !== "teacher";

  const [view, setView] = useState<"current" | "withdrawn">("current");
  const [rows, setRows] = useState<Classroom[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [adding, setAdding] = useState(false);
  const [grade, setGrade] = useState("");
  const [stream, setStream] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  // Fetching and storing are kept apart. `react-hooks/set-state-in-effect`
  // rejects an effect that calls a function which sets state, so the effect
  // below owns its own setState and this only returns data.
  const fetchRows = useCallback(
    () => api.get<Classroom[]>(`/api/classrooms?include_inactive=${view === "withdrawn"}`),
    [view],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchRows();
        if (cancelled) return;
        setRows(data);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e, "Could not load classes"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchRows]);

  /** Re-read after a change. Called from handlers, never from an effect. */
  const reload = useCallback(async () => {
    try {
      setRows(await fetchRows());
      setError(null);
    } catch (e) {
      setError(errorMessage(e, "Could not load classes"));
    }
  }, [fetchRows]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!grade) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await api.post<Classroom>("/api/classrooms", { grade, name: stream.trim() });
      setNotice(`${className(created)} added.`);
      setGrade("");
      setStream("");
      setAdding(false);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not add the class"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: Classroom) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      // The server decides whether this is a deletion or a withdrawal, and
      // says why. Reporting its own words avoids the interface claiming
      // something was deleted when it was kept.
      const result = await api.del<Removal>(`/api/classrooms/${row.class_id}`);
      setNotice(result.detail);
      setConfirming(null);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not remove the class"));
    } finally {
      setBusy(false);
    }
  }

  async function restore(row: Classroom) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.post<Restore>(`/api/classrooms/${row.class_id}/restore`);
      setNotice(result.detail);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not restore the class"));
    } finally {
      setBusy(false);
    }
  }

  // The withdrawn view asks the API for everything, then keeps only the
  // withdrawn classes - two clean lists instead of one mixed one.
  const shown =
    rows === null ? null : rows.filter((r) => (view === "withdrawn" ? !r.is_active : r.is_active));

  return (
    <>
      <PageHeader
        title="Classes"
        description="The classes at your school."
        actions={
          isAdmin && !adding ? (
            <Button onClick={() => setAdding(true)} className="w-full sm:w-auto">
              Add a class
            </Button>
          ) : undefined
        }
      />

      {isAdmin && adding && (
        <Card className="mb-6 p-4 sm:p-5">
          <form onSubmit={create}>
            <h2 className="text-base font-semibold text-ink">Add a class</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="text-sm font-medium text-ink">Grade</span>
                <select
                  required
                  value={grade}
                  onChange={(e) => setGrade(e.target.value)}
                  className="mt-1.5 block min-h-11 w-full rounded-md border border-line-strong
                             bg-surface px-3 text-base text-ink focus:border-ink focus:outline-none"
                >
                  <option value="" disabled>
                    Choose a grade
                  </option>
                  {GRADES.map((g) => (
                    <option key={g} value={g}>
                      {g}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-sm font-medium text-ink">
                  Stream <span className="font-normal text-ink-subtle">(optional)</span>
                </span>
                <input
                  value={stream}
                  maxLength={100}
                  onChange={(e) => setStream(e.target.value)}
                  placeholder="e.g. Blue"
                  className="mt-1.5 block min-h-11 w-full rounded-md border border-line-strong
                             bg-surface px-3 text-base text-ink placeholder:text-ink-subtle
                             focus:border-ink focus:outline-none"
                />
              </label>
            </div>
            <p className="mt-2 text-sm text-ink-subtle">
              Add a stream if your school has more than one class in this grade.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button type="submit" disabled={busy || !grade}>
                {busy ? "Adding…" : "Add class"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setAdding(false);
                  setGrade("");
                  setStream("");
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <div
        role="group"
        aria-label="Which classes to show"
        className="mb-4 inline-flex rounded-md border border-line-strong bg-surface p-0.5"
      >
        {(["current", "withdrawn"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={view === value}
            onClick={() => {
              setView(value);
              setRows(null);
              setConfirming(null);
            }}
            className={`min-h-10 rounded px-4 text-sm font-medium
                        ${view === value ? "bg-sunken text-ink" : "text-ink-muted hover:text-ink"}`}
          >
            {value === "current" ? "Current" : "Withdrawn"}
          </button>
        ))}
      </div>

      <div className="mb-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
      </div>

      {shown === null && !error && <Loading what="classes" />}

      {shown && shown.length === 0 && (
        <Empty
          title={view === "current" ? "No classes yet" : "No withdrawn classes"}
          action={
            view === "current" && isAdmin && !adding ? (
              <Button onClick={() => setAdding(true)}>Add a class</Button>
            ) : undefined
          }
        >
          {view === "withdrawn"
            ? "A class with recorded answers is withdrawn rather than deleted when it’s removed, and appears here so it can be restored."
            : isAdmin
              ? "Add your first class, then its learners."
              : "Your head teacher adds classes. Once they have, they’ll appear here."}
        </Empty>
      )}

      {shown && shown.length > 0 && (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
          {shown.map((row) => {
            const asking = confirming === row.class_id;
            return (
              <li key={row.class_id}>
                <div className="flex items-center">
                  <Link
                    href={`/classrooms/${row.class_id}`}
                    className="flex min-h-18 min-w-0 flex-1 items-center gap-3.5 px-4 py-3 hover:bg-sunken"
                  >
                    {/* Neutral, not blue: blue is reserved for levels. */}
                    <span
                      aria-hidden="true"
                      className={`flex size-12 shrink-0 flex-col items-center justify-center rounded-lg
                                  border border-line bg-sunken
                                  ${row.is_active ? "text-ink" : "text-ink-subtle"}`}
                    >
                      <span className="text-[9px] font-semibold uppercase leading-none tracking-wider text-ink-subtle">
                        Grade
                      </span>
                      <span className="mt-0.5 text-xl font-semibold leading-none tabular-nums">
                        {gradeNumber(row.grade)}
                      </span>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block truncate text-base font-semibold
                                    ${row.is_active ? "text-ink" : "text-ink-muted"}`}
                      >
                        {className(row)}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
                        {learners(row.student_count)}
                        {!row.is_active && <Badge>Withdrawn</Badge>}
                      </span>
                    </span>
                    <span aria-hidden="true" className="text-xl leading-none text-ink-subtle">
                      ›
                    </span>
                  </Link>

                  {isAdmin && row.is_active && !asking && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setConfirming(row.class_id)}
                      className="mr-2 min-h-11 shrink-0 rounded-md px-3 text-sm font-medium
                                 text-ink-muted hover:bg-risk-fill hover:text-risk disabled:opacity-50"
                    >
                      Remove
                    </button>
                  )}
                  {isAdmin && !row.is_active && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy}
                      onClick={() => restore(row)}
                      className="mr-3 shrink-0"
                    >
                      Restore
                    </Button>
                  )}
                </div>

                {asking && (
                  <div
                    role="alertdialog"
                    aria-label={`Remove ${className(row)}`}
                    className="border-t border-line bg-risk-fill px-4 py-3"
                  >
                    <p className="text-[15px] text-ink">
                      Remove <strong>{className(row)}</strong>? If its learners have
                      answered anything, it’s withdrawn instead and can be restored.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button variant="danger" disabled={busy} onClick={() => remove(row)}>
                        {busy ? "Removing…" : "Remove class"}
                      </Button>
                      <Button variant="secondary" disabled={busy} onClick={() => setConfirming(null)}>
                        Keep it
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
