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
 * **One learner at a time** (24 October). The learners-by-questions grid
 * needed sideways scrolling and 32-pixel cells on a phone, which is where
 * teachers mark. Now a teacher opens a learner, marks each question Right,
 * Wrong or Blank with full-size buttons, and moves to the next learner. On a
 * wide screen the grid stays, read-only, as a summary of what is marked.
 *
 * **The questions are a saved paper quiz** (21 October), not every question in
 * the strand: the teacher picks a length, the server picks the questions,
 * and the same set is on the printed sheet the class wrote on. The newest
 * paper quiz for the strand opens by default - usually the one just printed.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { type QuizLength, QuizLengthPicker } from "@/components/QuizLength";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  Empty,
  IconTile,
  Loading,
  Note,
  PageHeader,
  Select,
} from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { initials } from "@/lib/people";
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
  // The learner being marked; null shows the list of learners.
  const [current, setCurrent] = useState<string | null>(null);
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
        setCurrent(null);
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
  /** Right, wrong, or null for blank (not attempted). */
  function setMark(studentId: string, itemId: string, mark: Mark | null) {
    const k = key(studentId, itemId);
    if (locked.has(k)) return;
    setGrid((g) => {
      const next = { ...g };
      if (mark === null) delete next[k];
      else next[k] = mark;
      return next;
    });
  }

  /** Mark every open question for one learner; null clears them. */
  function markRow(studentId: string, mark: Mark | null) {
    setGrid((g) => {
      const next = { ...g };
      for (const item of items) {
        const k = key(studentId, item.item_id);
        if (locked.has(k)) continue;
        if (mark === null) delete next[k];
        else next[k] = mark;
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
          : `${receipt.detail} Use Record levels on the class page to update ` +
            "learners’ levels.",
      );
      // Landed. A new identifier, so the next submission is new work.
      setBatchId(newBatchId());
      const answered = await api.get<AnsweredPairs>(
        `/api/assessments/answered/${classId}/${strandId}`,
      );
      setLocked(new Set(answered.answered));
      setGrid({});
      setCurrent(null);
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
  const chosen = strands.find((s) => s.strand_id === strandId);
  const number = (n: number) => numbers[n] ?? n + 1;

  /** How far a learner's marking has got: marked now, recorded before, open. */
  function progress(studentId: string) {
    let marking = 0;
    let recorded = 0;
    for (const item of items) {
      const k = key(studentId, item.item_id);
      if (locked.has(k)) recorded += 1;
      else if (grid[k]) marking += 1;
    }
    return { marking, recorded, open: items.length - recorded };
  }

  const learner = learners.find((l) => l.student_id === current) ?? null;
  const at = learner ? learners.indexOf(learner) : -1;

  return (
    <>
      <PageHeader
        back={{ href: `/classrooms/${classId}`, label: title }}
        eyebrow={title}
        title="Mark a paper quiz"
        description="Make a quiz, print it for the class, then mark each learner’s answers here. Nothing is saved until you submit."
      />

      <div className="space-y-3">
        <Note tone="error">{error}</Note>
        <Note tone="ok">{notice}</Note>
      </div>

      {!ready && <Loading what="the class" />}

      {ready && !strands.some((s) => s.active_items > 0) && (
        <Note>
          This class has no strands with approved questions yet. Open a strand on the class
          page to write questions or have the AI write some.
        </Note>
      )}

      {ready && strands.length > 0 && (
        <Card className="mt-4 p-4 sm:p-6">
          <h2 className="flex items-center gap-3 text-lg font-semibold text-ink">
            <IconTile name="paper" />
            The quiz
          </h2>
          <div className="mt-4 space-y-4">
            <Select
              label="Strand"
              value={strandId}
              onChange={(e) => setStrandId(e.target.value)}
              hint={
                strands.some((s) => s.active_items === 0)
                  ? "A greyed-out strand has no approved questions yet."
                  : undefined
              }
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
            </Select>

            {quizzes.length > 0 && (
              <Select label="Quiz" value={quizId} onChange={(e) => setQuizId(e.target.value)}>
                {quizzes.map((q) => (
                  <option key={q.quiz_id} value={q.quiz_id}>
                    {q.questions} questions
                    {q.created_at && ` · made ${new Date(q.created_at).toLocaleString()}`}
                  </option>
                ))}
              </Select>
            )}

            {quizId && (
              <ButtonLink href={`/classrooms/${classId}/quizzes/${quizId}/print`}>
                <Icon name="paper" className="size-4" /> Print question sheet
              </ButtonLink>
            )}

            {strandId && (
              <details className="group rounded-xl border border-line" open={quizzes.length === 0}>
                <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between rounded-xl px-3.5 text-[15px] font-semibold text-ink hover:bg-sunken">
                  <span className="flex items-center gap-2">
                    <Icon name="plus" className="size-4 text-brand-strong" />
                    {quizzes.length > 0 ? "Make a new quiz" : "Make a quiz"}
                  </span>
                  <Icon name="chevronRight" className="size-4 text-ink-subtle transition-transform group-open:rotate-90" />
                </summary>
                <div className="space-y-3 border-t border-line p-3.5">
                  <QuizLengthPicker
                    value={length}
                    onChange={setLength}
                    available={chosen?.active_items}
                  />
                  <Button variant="secondary" disabled={busy} onClick={makeQuiz}>
                    {busy ? "Making…" : "Make quiz"}
                  </Button>
                </div>
              </details>
            )}

            {withdrawn > 0 && quizId && (
              <Note tone="warn">
                {withdrawn} {withdrawn === 1 ? "question was" : "questions were"} reported or
                retired since this quiz was made, so {withdrawn === 1 ? "it is" : "they are"}{" "}
                left out. The others keep their numbers from the sheet.
              </Note>
            )}
          </div>
        </Card>
      )}

      {ready && learners.length === 0 && !error && (
        <div className="mt-6">
          <Empty icon="users">
            No learners enrolled.{" "}
            <Link href={`/classrooms/${classId}/roll`} className="underline underline-offset-2">
              Enrol some on the roll
            </Link>
            .
          </Empty>
        </div>
      )}

      {ready && quizId && items.length === 0 && learners.length > 0 && !error && (
        <div className="mt-6">
          <Empty>
            Every question in this quiz has since been reported or retired. Make a new quiz.
          </Empty>
        </div>
      )}

      {/* --- one learner ------------------------------------------------- */}
      {learner && items.length > 0 && (
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

            {progress(learner.student_id).open > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="md" variant="secondary" onClick={() => markRow(learner.student_id, "correct")}>
                  All right
                </Button>
                <Button size="md" variant="secondary" onClick={() => markRow(learner.student_id, "wrong")}>
                  All wrong
                </Button>
                <Button size="md" variant="ghost" onClick={() => markRow(learner.student_id, null)}>
                  Clear
                </Button>
              </div>
            )}

            <ol className="mt-4 divide-y divide-line">
              {items.map((item, n) => {
                const k = key(learner.student_id, item.item_id);
                const isLocked = locked.has(k);
                const mark = grid[k] ?? null;
                return (
                  <li key={item.item_id} className="py-4">
                    <p className="flex gap-2.5 text-[15px] text-ink">
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-bold text-ink-muted">
                        {number(n)}
                      </span>
                      <span className="min-w-0">{item.question_text}</span>
                    </p>
                    {isLocked ? (
                      <div className="mt-2">
                        <Badge>Recorded earlier</Badge>
                      </div>
                    ) : (
                      <div
                        role="radiogroup"
                        aria-label={`Question ${number(n)} for ${learner.name}`}
                        className="mt-2 grid grid-cols-3 gap-1 rounded-xl bg-sunken p-1"
                      >
                        {(
                          [
                            ["correct", "✓ Right"],
                            ["wrong", "✗ Wrong"],
                            [null, "Blank"],
                          ] as const
                        ).map(([value, label]) => (
                          <button
                            key={label}
                            type="button"
                            role="radio"
                            aria-checked={mark === value}
                            onClick={() => setMark(learner.student_id, item.item_id, value)}
                            className={`min-h-11 rounded-lg text-[15px] font-semibold transition-all ${
                              mark === value
                                ? value === null
                                  ? "bg-surface text-ink shadow-soft"
                                  : "bg-action text-action-ink"
                                : "text-ink-muted hover:bg-sunken hover:text-ink"
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
            <p className="mt-2 text-sm text-ink-muted">
              Blank means the learner didn’t attempt it. A blank is left out of their level;
              a wrong answer counts against it.
            </p>

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

      {/* --- every learner ------------------------------------------------ */}
      {!learner && ready && learners.length > 0 && items.length > 0 && (
        <section aria-labelledby="learners-heading" className="mt-6">
          <h2 id="learners-heading" className="mb-3 flex items-center gap-2.5 text-lg font-semibold text-ink">
            <IconTile name="users" size="sm" />
            Mark each learner
          </h2>
          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {learners.map((l) => {
                const p = progress(l.student_id);
                const status =
                  p.open === 0
                    ? "Recorded"
                    : p.marking === 0
                      ? p.recorded > 0
                        ? `${p.open} to mark · ${p.recorded} recorded earlier`
                        : "Not marked"
                      : `${p.marking} of ${p.open} marked`;
                return (
                  <li key={l.student_id}>
                    <button
                      type="button"
                      onClick={() => {
                        setCurrent(l.student_id);
                        window.scrollTo({ top: 0 });
                      }}
                      className="group flex min-h-16 w-full items-center justify-between gap-3 px-4
                                 py-3 text-left hover:bg-sunken"
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span
                          aria-hidden="true"
                          className={`flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                            p.open === 0 || (p.open > 0 && p.marking === p.open)
                              ? "bg-action text-action-ink"
                              : "bg-sunken text-ink-muted"
                          }`}
                        >
                          {p.open === 0 || (p.open > 0 && p.marking === p.open) ? (
                            <Icon name="check" className="size-4" strokeWidth={2.4} />
                          ) : (
                            initials(l.name)
                          )}
                        </span>
                        <span className="min-w-0 truncate text-[15px] font-semibold text-ink">
                          {l.name}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        {p.open > 0 && p.marking === p.open ? (
                          <Badge tone="ok">Marked</Badge>
                        ) : (
                          <span className="text-sm text-ink-muted">{status}</span>
                        )}
                        <Icon
                          name="chevronRight"
                          className="size-4 text-ink-subtle transition-transform group-hover:translate-x-0.5"
                        />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Card>

          {/* Wide screens: the whole class at a glance, read-only. */}
          <div className="mt-6 hidden overflow-x-auto rounded-2xl border border-line bg-surface p-4 shadow-soft md:block">
            <table className="border-separate border-spacing-0.5 text-sm">
              <caption className="mb-2 text-left text-sm text-ink-muted">
                Summary: ✓ right, ✗ wrong, · recorded earlier, empty not marked. Open a
                learner to mark.
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="sticky left-0 z-10 bg-surface px-2 py-2 text-left font-medium text-ink">
                    Learner
                  </th>
                  {items.map((item, n) => (
                    <th
                      key={item.item_id}
                      scope="col"
                      title={item.question_text}
                      className="px-1 py-2 text-center text-xs font-medium text-ink-muted"
                    >
                      {number(n)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {learners.map((l) => (
                  <tr key={l.student_id}>
                    <th scope="row" className="sticky left-0 z-10 bg-surface px-2 py-1 text-left font-normal whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => setCurrent(l.student_id)}
                        className="text-ink underline-offset-2 hover:underline"
                      >
                        {l.name}
                      </button>
                    </th>
                    {items.map((item) => {
                      const k = key(l.student_id, item.item_id);
                      const isLocked = locked.has(k);
                      const mark = grid[k];
                      return (
                        <td
                          key={item.item_id}
                          className={`size-8 rounded-md border text-center ${
                            isLocked
                              ? "border-line bg-sunken text-ink-muted"
                              : mark === "correct"
                                ? "border-action bg-action text-action-ink"
                                : mark === "wrong"
                                  ? "border-line-strong bg-surface text-ink"
                                  : "border-line bg-surface"
                          }`}
                        >
                          {isLocked ? "·" : mark === "correct" ? "✓" : mark === "wrong" ? "✗" : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Stays in reach while marking, above the phone's tab bar. */}
      {marked > 0 && (
        <div className="sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-10 mt-6 md:bottom-4">
          <Card className="flex flex-wrap items-center justify-between gap-3 border-action/30 p-3 pl-4 shadow-lift">
            <span className="flex items-center gap-2 text-[15px] font-semibold text-ink">
              <span aria-hidden className="size-2 animate-pulse rounded-full bg-accent" />
              {marked} {marked === 1 ? "answer" : "answers"} marked, not saved yet
            </span>
            <Button disabled={busy} onClick={submit}>
              <Icon name="save" className="size-4" />
              {busy ? "Saving…" : "Submit"}
            </Button>
          </Card>
        </div>
      )}
    </>
  );
}
