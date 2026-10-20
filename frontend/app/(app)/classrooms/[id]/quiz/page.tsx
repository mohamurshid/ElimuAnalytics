"use client";

/**
 * Marking a quiz: learners down, items across.
 *
 * This is the page that finally lets a teacher create the data the rest of
 * the system measures. Until now every response in the database came from
 * the seed.
 *
 * Four decisions, each forced by something in the backend rather than chosen
 * for looks:
 *
 * **Cells are tri-state, not a checkbox.** Blank, correct, wrong. A checkbox
 * conflates "wrong" with "not attempted", and the response matrix treats
 * those as entirely different things - an unanswered item is excluded from
 * the estimate, a wrong one pulls it down. Submitting a blank as 0 would bias
 * every ability estimate in the class downward.
 *
 * **Pairs already recorded are locked.** The matrix holds one cell per
 * learner and item, so re-answering is refused; without knowing which pairs
 * exist, the grid would let a teacher tick one and then have the whole batch
 * rejected for a reason they could not have seen.
 *
 * **One batch, one identifier, generated once.** `client_batch_id` is made
 * when the page loads a fresh grid and reused on every retry, so a submission
 * that times out and is sent again is recognised as the same work rather than
 * recorded twice. It is only regenerated after a batch is known to have
 * landed.
 *
 * **Nothing is saved until Submit.** The grid is local state. A half-marked
 * class is not a half-recorded assessment.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button, Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type {
  AnsweredPairs,
  AssessmentReceipt,
  Classroom,
  Item,
  Strand,
  Student,
} from "@/lib/types";

type Mark = "correct" | "wrong";
type Grid = Record<string, Mark>; // "studentId:itemId" -> mark

const key = (studentId: string, itemId: string) => `${studentId}:${itemId}`;

function newBatchId(): string {
  // The device generates it, not the server: only the device can tell a retry
  // from a genuine second submission of identical answers.
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function QuizPage() {
  const { id: classId } = useParams<{ id: string }>();

  const [strands, setStrands] = useState<Strand[]>([]);
  const [strandId, setStrandId] = useState<string>("");
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [learners, setLearners] = useState<Student[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [locked, setLocked] = useState<Set<string>>(new Set());

  const [grid, setGrid] = useState<Grid>({});
  const [batchId, setBatchId] = useState<string>(newBatchId);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  /* --- load the class and the strand list ------------------------------ */
  const fetchContext = useCallback(
    () =>
      Promise.all([
        api.get<Classroom[]>("/api/classrooms"),
        // Only the class's strands, and only those with questions to ask.
        api.get<Strand[]>(`/api/classrooms/${classId}/strands`),
        api.get<Student[]>(`/api/classrooms/${classId}/students`),
      ]),
    [classId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [classes, allStrands, roll] = await fetchContext();
        if (cancelled) return;
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
        const usable = allStrands.filter((s) => s.active_items > 0);
        setStrands(usable);
        setLearners(roll);
        setStrandId((current) => current || usable[0]?.strand_id || "");
        setError(null);
        setReady(true);
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "No such classroom at your school."
            : errorMessage(e, "Could not load the class"),
        );
        setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchContext, classId]);

  /* --- load the items and what is already answered --------------------- */
  const fetchStrand = useCallback(
    (strand: string) =>
      Promise.all([
        api.get<Item[]>(`/api/items?strand_id=${strand}`),
        api.get<AnsweredPairs>(`/api/assessments/answered/${classId}/${strand}`),
      ]),
    [classId],
  );

  useEffect(() => {
    if (!strandId) return;
    let cancelled = false;
    (async () => {
      try {
        const [strandItems, answered] = await fetchStrand(strandId);
        if (cancelled) return;
        setItems(strandItems);
        setLocked(new Set(answered.answered));
        setGrid({});
        setBatchId(newBatchId());
        setError(null);
      } catch (e) {
        if (!cancelled) setError(errorMessage(e, "Could not load the items"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [strandId, fetchStrand]);

  /* --- marking ---------------------------------------------------------- */
  function cycle(studentId: string, itemId: string) {
    const k = key(studentId, itemId);
    if (locked.has(k)) return;
    setGrid((current) => {
      const next = { ...current };
      if (next[k] === undefined) next[k] = "correct";
      else if (next[k] === "correct") next[k] = "wrong";
      else delete next[k]; // back to not attempted
      return next;
    });
  }

  function markRow(studentId: string, mark: Mark) {
    setGrid((current) => {
      const next = { ...current };
      for (const item of items) {
        const k = key(studentId, item.item_id);
        if (!locked.has(k)) next[k] = mark;
      }
      return next;
    });
  }

  const marked = Object.keys(grid).length;

  async function submit() {
    if (marked === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const receipt = await api.post<AssessmentReceipt>("/api/assessments", {
        client_batch_id: batchId,
        class_id: classId,
        strand_id: strandId,
        responses: Object.entries(grid).map(([k, mark]) => {
          const [student_id, item_id] = k.split(":");
          return { student_id, item_id, correct: mark === "correct" };
        }),
      });
      setNotice(
        receipt.duplicate
          ? `${receipt.detail} (${receipt.responses_recorded} responses)`
          : `${receipt.detail} Run an assessment on the heatmap to fold them ` +
            "into ability estimates.",
      );
      // Landed. A new identifier, so the next submission is new work.
      setBatchId(newBatchId());
      const [, answered] = await fetchStrand(strandId);
      setLocked(new Set(answered.answered));
      setGrid({});
    } catch (e) {
      // The identifier is deliberately NOT regenerated here: if this failed
      // after the server recorded it, resending the same id is recognised as
      // the same batch rather than duplicating the work.
      setError(errorMessage(e, "Could not submit"));
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

      <h1 className="mt-2 text-2xl font-semibold">{title} — mark a quiz</h1>
      <p className="mt-1 max-w-3xl text-sm text-neutral-600">
        Click a cell to cycle it: blank → correct → wrong → blank. Leave a cell
        blank if the learner did not attempt the item — a blank is excluded
        from their estimate, while a wrong answer counts against it, and
        recording one as the other moves the numbers.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="font-medium">Strand</span>
          <select
            value={strandId}
            onChange={(e) => setStrandId(e.target.value)}
            className="mt-1 block rounded border border-neutral-300 px-3 py-1.5
                       text-sm"
          >
            {strands.map((s) => (
              <option key={s.strand_id} value={s.strand_id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <Button disabled={busy || marked === 0} onClick={submit}>
          {busy ? "Submitting…" : `Submit ${marked} response(s)`}
        </Button>
      </div>

      <div className="mt-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
        {ready && strands.length === 0 && (
          <Note>
            This class has no strands with questions yet. Add a strand on the class page; questions for it come with question generation.
          </Note>
        )}
      </div>

      {!ready && (
        <div className="mt-6">
          <Loading what="the class" />
        </div>
      )}

      {ready && learners.length === 0 && !error && (
        <div className="mt-6">
          <Empty>
            No learners enrolled.{" "}
            <Link
              href={`/classrooms/${classId}/roll`}
              className="underline underline-offset-2"
            >
              Enrol some on the roll
            </Link>
            .
          </Empty>
        </div>
      )}

      {ready && learners.length > 0 && items.length > 0 && (
        <div className="mt-6 overflow-x-auto">
          <table className="border-separate border-spacing-0.5 text-sm">
            <caption className="sr-only">
              Marking grid: learners by items. Each cell is blank, correct or
              wrong; cells already recorded are locked.
            </caption>
            <thead>
              <tr>
                <th
                  scope="col"
                  className="sticky left-0 z-10 bg-[var(--background)] px-2 py-2
                             text-left font-medium"
                >
                  Learner
                </th>
                {items.map((item, n) => (
                  <th
                    key={item.item_id}
                    scope="col"
                    title={item.question_text}
                    className="px-1 py-2 text-center text-xs font-medium"
                  >
                    {n + 1}
                  </th>
                ))}
                <th scope="col" className="px-2 py-2 text-left font-medium">
                  All
                </th>
              </tr>
            </thead>
            <tbody>
              {learners.map((learner) => (
                <tr key={learner.student_id}>
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-[var(--background)] px-2 py-1
                               text-left font-normal whitespace-nowrap"
                  >
                    {learner.name}
                  </th>

                  {items.map((item) => {
                    const k = key(learner.student_id, item.item_id);
                    const isLocked = locked.has(k);
                    const mark = grid[k];
                    const label = isLocked
                      ? "·"
                      : mark === "correct"
                        ? "✓"
                        : mark === "wrong"
                          ? "✗"
                          : "";
                    return (
                      <td key={item.item_id} className="p-0">
                        <button
                          type="button"
                          disabled={isLocked}
                          onClick={() => cycle(learner.student_id, item.item_id)}
                          title={
                            isLocked
                              ? "Already recorded. The matrix holds one response per learner and item."
                              : item.question_text
                          }
                          aria-label={`${learner.name}, item ${item.question_text}: ${
                            isLocked ? "already recorded" : (mark ?? "not attempted")
                          }`}
                          className={`h-8 w-8 border text-sm font-medium
                            ${
                              isLocked
                                ? "cursor-not-allowed border-neutral-200 bg-neutral-100 text-neutral-400"
                                : mark === "correct"
                                  ? "border-neutral-900 bg-neutral-900 text-white"
                                  : mark === "wrong"
                                    ? "border-neutral-900 bg-white text-neutral-900"
                                    : "border-neutral-300 bg-white hover:bg-neutral-100"
                            }`}
                        >
                          {label}
                        </button>
                      </td>
                    );
                  })}

                  <td className="px-2 py-1 whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => markRow(learner.student_id, "correct")}
                      className="mr-1 rounded border border-neutral-300 px-2
                                 py-0.5 text-xs hover:bg-neutral-100"
                    >
                      ✓
                    </button>
                    <button
                      type="button"
                      onClick={() => markRow(learner.student_id, "wrong")}
                      className="rounded border border-neutral-300 px-2 py-0.5
                                 text-xs hover:bg-neutral-100"
                    >
                      ✗
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-4 text-xs text-neutral-500">
            Greyed cells are already recorded and cannot be marked again: the
            response matrix holds one answer per learner and item, so a second
            one would overwrite the first and change every estimate derived
            from it. Hover an item number to read the question.
          </p>
        </div>
      )}

      {ready && items.length === 0 && learners.length > 0 && !error && (
        <div className="mt-6">
          <Empty>This strand has no active items.</Empty>
        </div>
      )}
    </>
  );
}
