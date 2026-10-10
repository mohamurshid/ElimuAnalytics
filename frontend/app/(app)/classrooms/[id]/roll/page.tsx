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

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Classroom, Removal, Student } from "@/lib/types";
import { Button, Empty, Field, Loading, Note } from "@/components/ui";

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
      <Link
        href={`/classrooms/${classId}`}
        className="text-sm text-neutral-500 hover:text-neutral-900"
      >
        ← Competency heatmap
      </Link>

      <div className="mt-2 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">{title} — roll</h1>
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={showWithdrawn}
            onChange={(e) => setShowWithdrawn(e.target.checked)}
          />
          Show withdrawn
        </label>
      </div>
      {classroom && !classroom.is_active && (
        <p className="mt-1 text-sm text-neutral-500">
          This class has been withdrawn. Learners cannot be enrolled into it.
        </p>
      )}

      <div className="mt-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
      </div>

      {classroom?.is_active && (
        <form
          onSubmit={enrol}
          className="mt-6 flex flex-wrap items-end gap-3 rounded border
                     border-neutral-200 bg-white p-4"
        >
          <div className="w-72">
            <Field
              label="Learner name"
              required
              placeholder="Wanjiru A."
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy}>
            Enrol
          </Button>
        </form>
      )}

      <section className="mt-6">
        {!roll && !error && <Loading what="the roll" />}

        {roll && roll.length === 0 && !error && (
          <Empty>No learners enrolled yet.</Empty>
        )}

        {roll && roll.length > 0 && (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-neutral-300 text-left">
                <th className="py-2 pr-4 font-medium">Learner</th>
                <th className="py-2 pr-4 font-medium">Responses</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {roll.map((learner) => (
                <tr key={learner.student_id} className="border-b border-neutral-200">
                  <td className="py-2 pr-4">{learner.name}</td>
                  <td className="py-2 pr-4">
                    {learner.response_count}
                    {learner.response_count > 0 && (
                      <span
                        className="ml-2 text-xs text-neutral-500"
                        title="Removing this learner will withdraw the record
                               rather than delete it, because deleting would
                               cascade to these responses."
                      >
                        kept on removal
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {learner.is_active ? (
                      <span className="text-neutral-600">active</span>
                    ) : (
                      <span className="text-neutral-400">withdrawn</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {isAdmin && learner.is_active && (
                      <Button
                        variant="danger"
                        disabled={busy}
                        onClick={() => remove(learner)}
                      >
                        Remove
                      </Button>
                    )}
                    {isAdmin && !learner.is_active && (
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => restoreLearner(learner)}
                      >
                        Restore
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
