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
 *
 * **The columns are a saved paper quiz** (21 October), not every question in
 * the strand: the teacher picks a length, the server picks the questions,
 * and the same set is on the printed sheet the class wrote on. The newest
 * paper quiz for the strand opens by default - usually the one just printed.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { type QuizLength, QuizLengthPicker } from "@/components/QuizLength";
import { Button, ButtonLink, Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type {
  AnsweredPairs,
  AssessmentReceipt,
  Classroom,
  QuizItem,
  QuizSet,
  QuizSummary,
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
  const [items, setItems] = useState<QuizItem[]>([]);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [quizId, setQuizId] = useState("");
  const [withdrawn, setWithdrawn] = useState(0);
  const [numbers, setNumbers] = useState<number[]>([]);
  const [length, setLength] = useState<QuizLength>(10);
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
        // Every strand the class is assessed on; the first with questions is
        // chosen, since an empty one has nothing to ask.
        const usable = allStrands.filter((s) => s.active_items > 0);
        setStrands(allStrands);
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

  /* --- the strand's paper quizzes and what is already answered -------- */
  const fetchStrand = useCallback(
    (strand: string) =>
      Promise.all([
        api.get<QuizSummary[]>(
          `/api/classrooms/${classId}/quizzes?strand_id=${strand}&mode=paper`,
        ),
        api.get<AnsweredPairs>(`/api/assessments/answered/${classId}/${strand}`),
      ]),
    [classId],
  );

  useEffect(() => {
    if (!strandId) return;
    let cancelled = false;
    (async () => {
      try {
        const [recent, answered] = await fetchStrand(strandId);
        if (cancelled) return;
        setQuizzes(recent);
        setQuizId(recent[0]?.quiz_id ?? "");
        if (recent.length === 0) setItems([]);
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

  /* --- the chosen quiz's questions are the grid's columns --------------- */
  useEffect(() => {
    if (!quizId) return;
    let cancelled = false;
    api
      .get<QuizSet>(`/api/quizzes/${quizId}`)
      .then((quiz) => {
        if (cancelled) return;
        setItems(quiz.items);
        setNumbers(quiz.numbers);
        setWithdrawn(quiz.withdrawn);
        setGrid({});
      })
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the quiz")));
    return () => {
      cancelled = true;
    };
  }, [quizId]);

  async function makeQuiz() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const quiz = await api.post<QuizSet>(`/api/classrooms/${classId}/quizzes`, {
        strand_id: strandId,
        length,
        mode: "paper",
      });
      const [recent] = await fetchStrand(strandId);
      setQuizzes(recent);
      setQuizId(quiz.quiz_id);
    } catch (e) {
      setError(errorMessage(e, "Could not make the quiz"));
    } finally {
      setBusy(false);
    }
  }

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
      const answered = await api.get<AnsweredPairs>(
        `/api/assessments/answered/${classId}/${strandId}`,
      );
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
              // Listed even when empty, so a strand just added does not seem to
              // vanish: it is shown, greyed, with the reason it cannot be quizzed.
              <option key={s.strand_id} value={s.strand_id} disabled={s.active_items === 0}>
                {s.name}
                {s.active_items === 0 &&
                  (s.draft_items > 0
                    ? ` — ${s.draft_items} waiting for review`
                    : " — no questions yet")}
              </option>
            ))}
          </select>
        </label>
        {quizzes.length > 0 && (
          <label className="text-sm">
            <span className="font-medium">Quiz</span>
            <select
              value={quizId}
              onChange={(e) => setQuizId(e.target.value)}
              className="mt-1 block rounded border border-neutral-300 px-3 py-1.5 text-sm"
            >
              {quizzes.map((q) => (
                <option key={q.quiz_id} value={q.quiz_id}>
                  {q.questions} questions
                  {q.created_at && ` · made ${new Date(q.created_at).toLocaleString()}`}
                </option>
              ))}
            </select>
          </label>
        )}
        <Button disabled={busy || marked === 0} onClick={submit}>
          {busy ? "Submitting…" : `Submit ${marked} response(s)`}
        </Button>
      </div>

      {ready && strandId && (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-md border border-line p-3">
          <QuizLengthPicker
            value={length}
            onChange={setLength}
            available={strands.find((s) => s.strand_id === strandId)?.active_items}
          />
          <Button variant="secondary" disabled={busy} onClick={makeQuiz}>
            {quizzes.length > 0 ? "Make a new quiz" : "Make a quiz"}
          </Button>
          {quizId && (
            <ButtonLink
              href={`/classrooms/${classId}/quizzes/${quizId}/print`}
              variant="ghost"
            >
              Print question sheet
            </ButtonLink>
          )}
        </div>
      )}

      <div className="mt-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
        {withdrawn > 0 && quizId && (
          <Note tone="warn">
            {withdrawn} {withdrawn === 1 ? "question was" : "questions were"} reported or
            retired since this quiz was made, so {withdrawn === 1 ? "it is" : "they are"} left
            out of the grid. The other columns keep their numbers from the sheet.
          </Note>
        )}
        {ready && strandId && quizzes.length === 0 && (
          <Note>
            Choose how many questions, then make a quiz. Print the question sheet for the
            class, then mark their answers here.
          </Note>
        )}
        {ready && !strands.some((s) => s.active_items > 0) && (
          <Note>
            This class has no strands with questions yet. Add a strand on the class page; questions for it come with question generation.
          </Note>
        )}
        {ready && strands.some((s) => s.active_items === 0) && (
          <Note>
            A greyed-out strand can’t be quizzed until it has approved
            questions. Questions written for it wait for a teacher’s review first.
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
                    {numbers[n] ?? n + 1}
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

      {ready && quizId && items.length === 0 && learners.length > 0 && !error && (
        <div className="mt-6">
          <Empty>
            Every question in this quiz has since been reported or retired. Make a new quiz.
          </Empty>
        </div>
      )}
    </>
  );
}
