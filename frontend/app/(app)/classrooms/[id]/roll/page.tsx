"use client";

/**
 * One classroom's roll.
 *
 * The page a teacher spends time on, so two things are made explicit that an
 * API client would have to infer.
 *
 * **Response counts are shown next to every learner.** They are what decides
 * whether removing that learner deletes the record or withdraws it, and a
 * teacher should be able to see that before clicking rather than discover it
 * afterwards.
 *
 * **A withdrawal explains itself in the server's words.** "Withdrawn, not
 * deleted, because 12 responses are attached" is a different fact from
 * "deleted", and paraphrasing it in the interface would eventually drift from
 * what the backend actually did.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Classroom, Removal, Student } from "@/lib/types";
import { Icon } from "@/components/Icon";
import { Badge, Button, Card, Empty, Field, Loading, Note, PageHeader, Segmented } from "@/components/ui";
import { initials } from "@/lib/people";

export default function ClassRollPage() {
  const params = useParams<{ id: string }>();
  const classId = params.id;

  const { profile } = useAuth();
  const isAdmin = profile?.role !== "teacher";

  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [roll, setRoll] = useState<Student[] | null>(null);
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");

  // Fetching and storing are kept apart, as in the list page: the effect
  // owns its own setState, and this only returns data.
  const fetchRoll = useCallback(
    () =>
      // The classroom list is already school-scoped, so finding this class in
      // it doubles as the permission check: another school's id is not there.
      Promise.all([
        api.get<Classroom[]>("/api/classrooms?include_inactive=true"),
        api.get<Student[]>(
          `/api/classrooms/${classId}/students?include_inactive=${showWithdrawn}`,
        ),
      ]),
    [classId, showWithdrawn],
  );

  const failure = useCallback(
    (e: unknown) =>
      e instanceof ApiError && e.status === 404
        ? "No such classroom at your school."
        : errorMessage(e, "Could not load the roll"),
    [],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [classes, learners] = await fetchRoll();
        if (cancelled) return;
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
        setRoll(learners);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(failure(e));
        setRoll([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchRoll, failure, classId]);

  /** Re-read after a change. Called from handlers, never from an effect. */
  const reload = useCallback(async () => {
    try {
      const [classes, learners] = await fetchRoll();
      setClassroom(classes.find((c) => c.class_id === classId) ?? null);
      setRoll(learners);
      setError(null);
    } catch (e) {
      setError(failure(e));
      setRoll([]);
    }
  }, [fetchRoll, failure, classId]);

  async function enrol(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.post<Student>(`/api/classrooms/${classId}/students`, { name });
      setName("");
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not enrol"));
    } finally {
      setBusy(false);
    }
  }

  async function restoreLearner(learner: Student) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.patch<Student>(`/api/students/${learner.student_id}`, {
        is_active: true,
      });
      setNotice(`${learner.name} was restored to the roll.`);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not restore"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(learner: Student) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.del<Removal>(
        `/api/students/${learner.student_id}`,
      );
      setNotice(`${learner.name}: ${result.detail}`);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not remove"));
    } finally {
      setBusy(false);
    }
  }

  const title = classroom
    ? `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`
    : "Classroom";

  return (
    <>
      <PageHeader
        back={{ href: `/classrooms/${classId}`, label: title }}
        eyebrow={title}
        title="Learners"
        description={
          classroom && !classroom.is_active
            ? "This class has been withdrawn. Learners cannot be enrolled into it."
            : roll
              ? `${roll.filter((l) => l.is_active).length} enrolled`
              : undefined
        }
        actions={
          <Segmented
            label="Which learners to show"
            value={showWithdrawn ? "all" : "current"}
            onChange={(v) => setShowWithdrawn(v === "all")}
            options={[
              { value: "current", label: "Current" },
              { value: "all", label: "Include withdrawn" },
            ]}
          />
        }
      />

      <div className="mb-4 space-y-3 empty:hidden">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
      </div>

      {classroom?.is_active && (
        <Card className="mb-6 p-4 sm:p-5">
          <form onSubmit={enrol} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Field
                label="Add a learner"
                name="learner-name"
                required
                placeholder="e.g. Wanjiru A."
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={busy}>
              <Icon name="plus" className="size-5" /> Enrol
            </Button>
          </form>
        </Card>
      )}

      <section>
        {!roll && !error && <Loading what="the roll" />}

        {roll && roll.length === 0 && !error && (
          <Empty icon="users">No learners enrolled yet.</Empty>
        )}

        {roll && roll.length > 0 && (
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface shadow-soft">
            {roll.map((learner) => (
              <li
                key={learner.student_id}
                className="flex flex-wrap items-center gap-3 px-4 py-3"
              >
                <span
                  aria-hidden="true"
                  className={`flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-bold
                              ${learner.is_active ? "bg-brand-fill text-brand-strong" : "bg-sunken text-ink-subtle"}`}
                >
                  {initials(learner.name)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={`block truncate font-semibold ${learner.is_active ? "text-ink" : "text-ink-muted"}`}>
                    {learner.name}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
                    {learner.response_count} {learner.response_count === 1 ? "answer" : "answers"}
                    {learner.response_count > 0 && learner.is_active && (
                      <span
                        className="text-xs text-ink-subtle"
                        title="Removing this learner will withdraw the record rather than delete it, because deleting would cascade to these responses."
                      >
                        · kept on removal
                      </span>
                    )}
                    {!learner.is_active && <Badge>Withdrawn</Badge>}
                  </span>
                </span>
                {isAdmin && learner.is_active && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => remove(learner)}
                    className="min-h-11 shrink-0 rounded-xl px-3 text-sm font-semibold text-ink-muted
                               hover:bg-risk-fill hover:text-risk disabled:opacity-50"
                  >
                    Remove
                  </button>
                )}
                {isAdmin && !learner.is_active && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => restoreLearner(learner)}
                  >
                    <Icon name="refresh" className="size-4" /> Restore
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
