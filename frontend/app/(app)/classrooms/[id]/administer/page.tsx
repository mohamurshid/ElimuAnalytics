"use client";

/**
 * Quiz mode: a learner answers on the teacher's device.
 *
 * The screen a child actually holds, and the only place in this application
 * where someone other than the signed-in teacher touches the tablet. That
 * single fact drives the whole design.
 *
 * **The tablet is signed in as the teacher.** A child holding it is holding a
 * session that can reach the competency heatmap - every classmate's ability
 * estimate, by name. So quiz mode is a containment boundary, not a page: no
 * navigation chrome, the browser's back button trapped, and leaving requires
 * the teacher's password. "A child could see other children's scores" is a
 * disclosure, not a cosmetic problem.
 *
 * **Identity is the teacher selecting a name before handing the device over.**
 * There are no learner accounts and no child PINs: issuing credentials to
 * primary-school children is a far larger data-protection surface than this
 * buys. The assumption is supervision, and it is written down as one rather
 * than hidden - see docs/PHASE3.md.
 *
 * **The device never learns the answers.** It receives questions and options
 * from the quiz endpoint, which has no field for the key, and submits the
 * option chosen. The server marks it. A learner cannot read the answer off
 * the network tab because it was never sent.
 *
 * **Answers are held until the teacher ends the session.** One batch, one
 * idempotency key, so a submission that times out and is retried is
 * recognised as the same work rather than recorded twice.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button, Field, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage, login } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type {
  AnsweredPairs,
  AssessmentReceipt,
  Classroom,
  Quiz,
  QuizItem,
  Strand,
  Student,
} from "@/lib/types";

type Phase = "setup" | "roster" | "answering" | "handback" | "locked";
type Answer = { student_id: string; item_id: string; selected_option: number };

function newBatchId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function AdministerPage() {
  const { id: classId } = useParams<{ id: string }>();
  const router = useRouter();
  const { profile } = useAuth();

  const [phase, setPhase] = useState<Phase>("setup");
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [strands, setStrands] = useState<Strand[]>([]);
  const [strandId, setStrandId] = useState("");
  const [roll, setRoll] = useState<Student[]>([]);
  const [quiz, setQuiz] = useState<Quiz | null>(null);

  // Pairs that already have a response. A learner who answered an item in an
  // earlier session must not be asked it again: the response matrix holds one
  // cell per learner and item, so the server refuses a second answer - and
  // without this the child answers twelve questions and the whole batch is
  // rejected afterwards, which is the worst possible moment to find out.
  const [answered, setAnswered] = useState<Set<string>>(new Set());

  const [learner, setLearner] = useState<Student | null>(null);
  const [queue, setQueue] = useState<QuizItem[]>([]);
  const [position, setPosition] = useState(0);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [batchId, setBatchId] = useState(newBatchId);

  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  const inSession = phase !== "setup";

  /* --- trap the back button ------------------------------------------- */
  useEffect(() => {
    // The effect only registers while a session is running and tears the
    // listener down when one ends, so the handler never needs to re-check -
    // which is also why no ref is involved. Writing a ref during render is
    // what `react-hooks/refs` rightly objects to.
    if (!inSession) return;
    // A child pressing Back must not land on the dashboard. Pushing a state
    // and re-pushing it on popstate keeps the history pinned here. It is not
    // a hard lock - nothing in a browser is - but it stops the realistic
    // case, which is a bored eight-year-old tapping.
    history.pushState(null, "", location.href);
    const onPop = () => history.pushState(null, "", location.href);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [inSession]);

  /* --- load the class --------------------------------------------------- */
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
        const [classes, allStrands, learners] = await fetchContext();
        if (cancelled) return;
        setClassroom(classes.find((c) => c.class_id === classId) ?? null);
        const usable = allStrands.filter((s) => s.active_items > 0);
        setStrands(usable);
        setRoll(learners);
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

  /* --- session control -------------------------------------------------- */
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const [loaded, taken] = await Promise.all([
        api.get<Quiz>(`/api/assessments/quiz/${classId}/${strandId}`),
        api.get<AnsweredPairs>(
          `/api/assessments/answered/${classId}/${strandId}`,
        ),
      ]);
      if (loaded.items.length === 0) {
        setError(
          "No items in this strand have answer options, so none can be " +
            "answered on a device. A teacher can still mark them on the roll.",
        );
        return;
      }
      setQuiz(loaded);
      setAnswered(new Set(taken.answered));
      setAnswers([]);
      setDone(new Set());
      setBatchId(newBatchId());
      setPhase("roster");
    } catch (e) {
      setError(errorMessage(e, "Could not load the quiz"));
    } finally {
      setBusy(false);
    }
  }

  /** What this learner has not answered yet, in this strand. */
  const remainingFor = useCallback(
    (student: Student): QuizItem[] =>
      (quiz?.items ?? []).filter(
        (item) => !answered.has(`${student.student_id}:${item.item_id}`),
      ),
    [quiz, answered],
  );

  function handOver(student: Student) {
    const theirs = remainingFor(student);
    if (theirs.length === 0) return; // the roster disables this anyway
    setLearner(student);
    setQueue(theirs);
    setPosition(0);
    setPhase("answering");
  }

  function answer(optionIndex: number) {
    if (!learner || queue.length === 0) return;
    const item = queue[position];
    setAnswers((current) => [
      ...current,
      {
        student_id: learner.student_id,
        item_id: item.item_id,
        selected_option: optionIndex,
      },
    ]);
    // Held locally AND marked as taken, so a second hand-over in the same
    // session cannot ask the same question twice.
    setAnswered((current) =>
      new Set(current).add(`${learner.student_id}:${item.item_id}`),
    );

    if (position + 1 < queue.length) {
      setPosition(position + 1);
    } else {
      setDone((current) => new Set(current).add(learner.student_id));
      setPhase("handback");
    }
  }

  async function endSession() {
    if (answers.length === 0) {
      setPhase("setup");
      setNotice("Session ended. Nothing was recorded.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const receipt = await api.post<AssessmentReceipt>("/api/assessments", {
        client_batch_id: batchId,
        class_id: classId,
        strand_id: strandId,
        responses: answers,
      });
      setNotice(
        `${receipt.detail} ${done.size} learner(s) answered. Run an ` +
          "assessment on the heatmap to fold these into ability estimates.",
      );
      setAnswers([]);
      setDone(new Set());
      setBatchId(newBatchId());
      setPhase("setup");
    } catch (e) {
      // The batch id is NOT regenerated: if this failed after the server
      // recorded it, resending the same id is what stops a second copy.
      setError(errorMessage(e, "Could not submit — the answers are still held"));
    } finally {
      setBusy(false);
    }
  }

  /** Leaving requires proving the teacher is the one holding the device. */
  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    if (!profile) return;
    setBusy(true);
    setError(null);
    try {
      await login(profile.email, password);
      setPassword("");
      router.replace(`/classrooms/${classId}`);
    } catch {
      setPassword("");
      setError("That password is not correct. Still in quiz mode.");
    } finally {
      setBusy(false);
    }
  }

  const title = classroom
    ? `${classroom.grade}${classroom.name ? ` ${classroom.name}` : ""}`
    : "Classroom";

  /* --- setup: the only phase with a way out ---------------------------- */
  if (!inSession) {
    return (
      <>
        <h1 className="text-2xl font-semibold">{title} — administer a quiz</h1>
        <p className="mt-1 max-w-2xl text-sm text-neutral-600">
          Learners answer on this device, one at a time. You select who is
          answering before handing it over, and the tablet stays locked in quiz
          mode until you enter your password — so nobody can reach another
          learner&apos;s results from it.
        </p>

        <div className="mt-4 space-y-3">
          <Note tone="error">{error}</Note>
          <Note>{notice}</Note>
        </div>

        {!ready && (
          <div className="mt-6">
            <Loading what="the class" />
          </div>
        )}

        {ready && strands.length === 0 && (
          <div className="mt-6">
            <Note>
              This class has no strands with questions yet. Add a strand on the class page; questions for it come with question generation.
            </Note>
          </div>
        )}

        {ready && strands.length > 0 && (
          <div className="mt-6 flex flex-wrap items-end gap-4">
            <label className="text-sm">
              <span className="font-medium">Strand</span>
              <select
                value={strandId}
                onChange={(e) => setStrandId(e.target.value)}
                className="mt-1 block rounded border border-neutral-300 px-3
                           py-1.5 text-sm"
              >
                {strands.map((s) => (
                  <option key={s.strand_id} value={s.strand_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <Button disabled={busy || !strandId} onClick={start}>
              Start quiz session
            </Button>
          </div>
        )}
      </>
    );
  }

  /* --- in session: no chrome, no links, no way back -------------------- */
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto max-w-2xl px-6 py-10">
        {phase === "roster" && quiz && (
          <>
            <p className="text-sm text-neutral-500">
              {title} · {quiz.strand} · {quiz.items.length} questions
            </p>
            <h1 className="mt-1 text-2xl font-semibold">Who is answering?</h1>
            <p className="mt-1 text-sm text-neutral-600">
              Tap a name, then hand the device to that learner.
            </p>

            <div className="mt-4 space-y-3">
              <Note tone="error">{error}</Note>
            </div>

            <ul className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {roll.map((student) => {
                const left = remainingFor(student).length;
                const justFinished = done.has(student.student_id);
                const nothingLeft = left === 0;
                return (
                  <li key={student.student_id}>
                    <button
                      type="button"
                      disabled={nothingLeft}
                      onClick={() => handOver(student)}
                      className={`w-full rounded border px-3 py-3 text-left text-sm
                        ${
                          nothingLeft
                            ? "cursor-not-allowed border-neutral-200 bg-neutral-100 text-neutral-400"
                            : "border-neutral-300 bg-white hover:bg-neutral-100"
                        }`}
                    >
                      {student.name}
                      <span className="block text-xs">
                        {justFinished
                          ? "answered just now"
                          : nothingLeft
                            ? "already answered this strand"
                            : `${left} question(s) left`}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            {roll.every((s) => remainingFor(s).length === 0) && (
              <p className="mt-4 text-sm text-neutral-600">
                Every learner has already answered every item in this strand.
                Nothing further can be recorded here — one response per learner
                and item is all the measurement allows.
              </p>
            )}

            <div className="mt-8 flex flex-wrap items-center gap-3 border-t
                            border-neutral-200 pt-6">
              <Button disabled={busy} onClick={endSession}>
                {busy ? "Submitting…" : `End session (${answers.length} answers)`}
              </Button>
              <Button variant="secondary" onClick={() => setPhase("locked")}>
                Leave quiz mode
              </Button>
              <p className="w-full text-xs text-neutral-500">
                Answers are held on this device until you end the session.
                Ending it records them and returns you here.
              </p>
            </div>
          </>
        )}

        {phase === "answering" && learner && queue[position] && (
          <>
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium">{learner.name}</p>
              <p className="text-sm text-neutral-500">
                Question {position + 1} of {queue.length}
              </p>
            </div>

            <div
              aria-hidden
              className="mt-2 h-1 w-full rounded bg-neutral-200"
            >
              <div
                className="h-1 rounded bg-neutral-900"
                style={{
                  width: `${((position + 1) / queue.length) * 100}%`,
                }}
              />
            </div>

            <h1 className="mt-8 text-xl font-medium">
              {queue[position].question_text}
            </h1>

            <ul className="mt-6 space-y-3">
              {queue[position].options.map((option, index) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => answer(index)}
                    className="w-full rounded border border-neutral-300 bg-white
                               px-4 py-4 text-left hover:bg-neutral-100"
                  >
                    <span className="mr-3 font-medium text-neutral-500">
                      {String.fromCharCode(65 + index)}
                    </span>
                    {option}
                  </button>
                </li>
              ))}
            </ul>

            {/* No "back" and no "skip": a child correcting an earlier answer
                after seeing a later question is a different measurement, and
                there is no teacher watching the screen to adjudicate. */}
            <p className="mt-8 text-xs text-neutral-500">
              Choose the answer you think is right. You will not be told
              whether it was correct.
            </p>
          </>
        )}

        {phase === "handback" && learner && (
          <div className="py-20 text-center">
            <h1 className="text-2xl font-semibold">Finished, {learner.name}.</h1>
            <p className="mt-2 text-neutral-600">
              Please give the device back to your teacher.
            </p>
            <div className="mt-10">
              <Button variant="secondary" onClick={() => setPhase("roster")}>
                Teacher: continue
              </Button>
            </div>
          </div>
        )}

        {phase === "locked" && (
          <form onSubmit={unlock} className="mx-auto max-w-sm py-20">
            <h1 className="text-xl font-semibold">Leave quiz mode</h1>
            <p className="mt-1 text-sm text-neutral-600">
              Enter the password for {profile?.email} to return to the rest of
              the application.
            </p>

            <div className="mt-4">
              <Field
                label="Password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="mt-4">
              <Note tone="error">{error}</Note>
            </div>

            <div className="mt-6 flex gap-3">
              <Button type="submit" disabled={busy}>
                {busy ? "Checking…" : "Unlock"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setPassword("");
                  setError(null);
                  setPhase("roster");
                }}
              >
                Back to the quiz
              </Button>
            </div>

            {answers.length > 0 && (
              <p className="mt-6 text-xs text-neutral-500">
                {answers.length} answer(s) are still held and unrecorded. End
                the session first if you want them kept.
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
