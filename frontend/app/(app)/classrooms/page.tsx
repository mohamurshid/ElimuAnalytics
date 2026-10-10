"use client";

/**
 * The school's classrooms.
 *
 * Every row here came back scoped: the API returns the caller's own school
 * and nothing else, so there is no school filter in this interface and no way
 * to ask for one.
 *
 * Creating and withdrawing are school_admin actions. The buttons are hidden
 * from a plain teacher rather than shown and rejected - but the hiding is
 * cosmetic, and the server enforces it either way. An interface that only
 * hides is not access control.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Classroom, Removal, Restore } from "@/lib/types";
import { Button, Empty, Field, Loading, Note } from "@/components/ui";

export default function ClassroomsPage() {
  const { profile } = useAuth();
  const isAdmin = profile?.role !== "teacher";

  const [rows, setRows] = useState<Classroom[] | null>(null);
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [grade, setGrade] = useState("");
  const [name, setName] = useState("");

  // Fetching and storing are kept apart. `react-hooks/set-state-in-effect`
  // rejects an effect that calls a function which sets state, so the effect
  // below owns its own setState and this only returns data.
  const fetchRows = useCallback(
    () =>
      api.get<Classroom[]>(`/api/classrooms?include_inactive=${showWithdrawn}`),
    [showWithdrawn],
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
        if (!cancelled) setError(errorMessage(e, "Could not load classrooms"));
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
      setError(errorMessage(e, "Could not load classrooms"));
    }
  }, [fetchRows]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.post<Classroom>("/api/classrooms", { grade, name });
      setGrade("");
      setName("");
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not create the class"));
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
      const result = await api.post<Restore>(
        `/api/classrooms/${row.class_id}/restore`,
      );
      setNotice(result.detail);
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not restore the class"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Classrooms</h1>
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={showWithdrawn}
            onChange={(e) => setShowWithdrawn(e.target.checked)}
          />
          Show withdrawn
        </label>
      </div>
      <p className="mt-1 text-sm text-neutral-600">
        Classes at your school. Other schools&apos; classes are not returned by
        the API and cannot be reached from here. Removing a class withdraws it
        rather than deleting it when learners have answered anything — tick
        <em> Show withdrawn</em> to find and restore one.
      </p>

      <div className="mt-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
      </div>

      {isAdmin && (
        <form
          onSubmit={create}
          className="mt-6 flex flex-wrap items-end gap-3 rounded border
                     border-neutral-200 bg-white p-4"
        >
          <div className="w-40">
            <Field
              label="Grade"
              required
              placeholder="Grade 5"
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
            />
          </div>
          <div className="w-40">
            <Field
              label="Stream"
              placeholder="Blue"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy}>
            Add class
          </Button>
          <p className="w-full text-xs text-neutral-500">
            A stream name is optional, but most schools run more than one class
            per grade and grade alone cannot tell them apart.
          </p>
        </form>
      )}

      <section className="mt-6">
        {!rows && !error && <Loading what="classrooms" />}

        {rows && rows.length === 0 && (
          <Empty>
            No classrooms yet.
            {isAdmin
              ? " Add one above."
              : " A school administrator can add the first one."}
          </Empty>
        )}

        {rows && rows.length > 0 && (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-neutral-300 text-left">
                <th className="py-2 pr-4 font-medium">Class</th>
                <th className="py-2 pr-4 font-medium">Learners</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.class_id}
                  className="border-b border-neutral-200 align-middle"
                >
                  <td className="py-2 pr-4">
                    <Link
                      href={`/classrooms/${row.class_id}`}
                      className="font-medium underline underline-offset-2
                                 hover:text-neutral-600"
                    >
                      {row.grade}
                      {row.name ? ` ${row.name}` : ""}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">{row.student_count}</td>
                  <td className="py-2 pr-4">
                    {row.is_active ? (
                      <span className="text-neutral-600">active</span>
                    ) : (
                      <span className="text-neutral-400">withdrawn</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {isAdmin && row.is_active && (
                      <Button
                        variant="danger"
                        disabled={busy}
                        onClick={() => remove(row)}
                      >
                        Remove
                      </Button>
                    )}
                    {isAdmin && !row.is_active && (
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => restore(row)}
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
