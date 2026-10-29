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
 * a PIN the teacher chose when starting. "A child could see other children's
 * scores" is a disclosure, not a cosmetic problem.
 *
 * **A session PIN, not the account password** (24 October). Unlocking used to
 * sign in again with the teacher's password - but a teacher who signs in
 * with Google has no password, and would have been stuck in quiz mode. The
 * PIN is chosen when the session starts and lives only in this page. It is
 * no weaker than before: the lock was always this page's to enforce, and
 * closing the browser ends it either way. A teacher with a password can
 * still use it if they forget the PIN; one without is offered no such
 * button (25 October), and can set a password on their profile.
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

import { Icon } from "@/components/Icon";
import { type QuizLength, QuizLengthPicker } from "@/components/QuizLength";
import { Button, Card, Field, Loading, Note, PageHeader, Select } from "@/components/ui";
import { api, ApiError, errorMessage, login } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { initials } from "@/lib/people";
import type {
  AnsweredPairs,
  AssessmentReceipt,
  Classroom,
  Quiz,
  QuizItem,
  QuizSet,
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
  const [length, setLength] = useState<QuizLength>(10);
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

  // The session PIN: chosen at the start, needed to leave. Never sent anywhere.
  const [pin, setPin] = useState("");
  const [sessionPin, setSessionPin] = useState("");
  const [attempt, setAttempt] = useState("");
  const [usePassword, setUsePassword] = useState(false);
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
        // Every strand the class is assessed on; the first with questions is
        // chosen, since an empty one has nothing to ask.
        const usable = allStrands.filter((s) => s.active_items > 0);
        setStrands(allStrands);
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
  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (!/^\d{4}$/.test(pin)) {
      setError("Choose a 4-digit PIN. You’ll need it to leave quiz mode.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      // A saved quiz: the server chooses the questions once, so every
      // learner handed the device in this session gets the same set.
      const [loaded, taken] = await Promise.all([
        api.post<QuizSet>(`/api/classrooms/${classId}/quizzes`, {
          strand_id: strandId,
          length,
          mode: "device",
        }),
        api.get<AnsweredPairs>(`/api/assessments/answered/${classId}/${strandId}`),
      ]);
      if (loaded.items.length === 0) {
        setError(
          "None of this strand’s questions has answer options, so none can be " +
            "answered on a device. Use a paper quiz instead.",
        );
        return;
      }
      setQuiz(loaded);
      setAnswered(new Set(taken.answered));
      setAnswers([]);
      setDone(new Set());
      setBatchId(newBatchId());
      setSessionPin(pin);
      setPin("");
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
    setAnswered((current) => new Set(current).add(`${learner.student_id}:${item.item_id}`));

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
        `${receipt.detail} ${done.size} ${done.size === 1 ? "learner" : "learners"} ` +
          "answered. Use Record levels on the class page to update their levels.",
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

  function backToQuiz() {
    setAttempt("");
    setPassword("");
    setUsePassword(false);
    setError(null);
    setPhase("roster");
  }

  /** Leaving needs the session PIN - or, if forgotten, the account password. */
  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!usePassword) {
      if (attempt === sessionPin) {
        router.replace(`/classrooms/${classId}`);
      } else {
        setAttempt("");
        setError("That PIN is not right. Still in quiz mode.");
      }
      return;
    }
    if (!profile) return;
    setBusy(true);
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
  const chosen = strands.find((s) => s.strand_id === strandId);

  /* --- setup: the only phase with a way out ---------------------------- */
  if (!inSession) {
    return (
      <>
        <PageHeader
          back={{ href: `/classrooms/${classId}`, label: title }}
          eyebrow={title}
          title="Quiz on this device"
          description="Learners answer on this phone or tablet, one at a time. You choose who is answering before handing it over, and it stays in quiz mode until you enter your PIN — so no learner can reach anyone’s results from it."
        />

        <div className="space-y-3">
          <Note tone="error">{error}</Note>
          <Note tone="ok">{notice}</Note>
        </div>

        {!ready && <Loading what="the class" />}

        {ready && !strands.some((s) => s.active_items > 0) && (
          <div className="mt-4">
            <Note>
              This class has no strands with approved questions yet. Open a strand on the
              class page to write questions or have the AI write some.
            </Note>
          </div>
        )}

        {ready && strands.length > 0 && (
          <Card className="mt-4 p-4 sm:p-6">
            <form onSubmit={start} className="space-y-5">
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

              <QuizLengthPicker
                value={length}
                onChange={setLength}
                available={chosen?.active_items}
              />

              <Field
                label="Choose a 4-digit PIN"
                hint="You’ll need it to leave quiz mode. Don’t let learners see it."
                type="password"
                inputMode="numeric"
                autoComplete="off"
                maxLength={4}
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
              />

              <Button type="submit" disabled={busy || !strandId} className="w-full sm:w-auto">
                <Icon name="phone" className="size-5" />
                {busy ? "Starting…" : "Start quiz"}
              </Button>
            </form>
          </Card>
        )}
      </>
    );
  }

  /* --- in session: no chrome, no links, no way back -------------------- */
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-canvas">
      <div className="mx-auto max-w-2xl px-4 py-8 sm:px-6 sm:py-10">
        {phase === "roster" && quiz && (
          <>
            <p className="inline-flex items-center gap-1.5 rounded-full bg-brand-fill px-3 py-1 text-sm font-semibold text-brand-strong">
              <Icon name="lock" className="size-4" /> Quiz mode
            </p>
            <p className="mt-3 text-sm text-ink-muted">
              {title} · {quiz.strand} · {quiz.items.length} questions
            </p>
            <h1 className="mt-1 text-[28px] font-bold tracking-tight text-ink">
              Who is answering?
            </h1>
            <p className="mt-1 text-[15px] text-ink-muted">
              Tap a name, then hand the device to that learner.
            </p>

            <div className="mt-4 space-y-3">
              <Note tone="error">{error}</Note>
            </div>

            <ul className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
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
                      className={`flex min-h-18 w-full items-center gap-3 rounded-2xl border
                                  px-3 py-3 text-left transition-all ${
                                    nothingLeft
                                      ? "cursor-not-allowed border-line bg-sunken text-ink-subtle"
                                      : "border-line bg-surface text-ink shadow-soft hover:-translate-y-0.5 hover:shadow-lift active:scale-[0.98]"
                                  }`}
                    >
                      <span
                        aria-hidden="true"
                        className={`flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                          justFinished || nothingLeft
                            ? "bg-sunken text-ink-subtle"
                            : "bg-brand-fill text-brand-strong"
                        }`}
                      >
                        {justFinished || nothingLeft ? <Icon name="check" className="size-5" /> : initials(student.name)}
                      </span>
                      <span className="min-w-0">
                      <span className="block truncate text-[15px] font-semibold">{student.name}</span>
                      <span className="mt-0.5 block text-sm text-ink-muted">
                        {justFinished
                          ? "Finished just now"
                          : nothingLeft
                            ? "Already answered"
                            : `${left} ${left === 1 ? "question" : "questions"} left`}
                      </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            {roll.every((s) => remainingFor(s).length === 0) && (
              <div className="mt-4">
                <Note>
                  Every learner has already answered every question in this quiz. Each
                  learner answers a question once, so nothing more can be recorded here.
                </Note>
              </div>
            )}

            <div className="mt-8 space-y-3 border-t border-line pt-6">
              <div className="flex flex-wrap gap-2">
                <Button disabled={busy} onClick={endSession}>
                  {busy
                    ? "Saving…"
                    : answers.length === 0
                      ? "End session"
                      : `Save ${answers.length} ${answers.length === 1 ? "answer" : "answers"} and end`}
                </Button>
                <Button variant="secondary" onClick={() => setPhase("locked")}>
                  Leave quiz mode
                </Button>
              </div>
              <p className="text-sm text-ink-muted">
                Answers stay on this device until you end the session, which saves them.
              </p>
            </div>
          </>
        )}

        {phase === "answering" && learner && queue[position] && (
          <>
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-2 text-[15px] font-semibold text-ink">
                <span
                  aria-hidden="true"
                  className="flex size-8 items-center justify-center rounded-full bg-brand-fill text-xs font-bold text-brand-strong"
                >
                  {initials(learner.name)}
                </span>
                {learner.name}
              </p>
              <p className="rounded-full bg-sunken px-3 py-1 text-sm font-semibold tabular-nums text-ink-muted">
                {position + 1} / {queue.length}
              </p>
            </div>

            <div aria-hidden className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full bg-action transition-[width] duration-500"
                style={{ width: `${((position + 1) / queue.length) * 100}%` }}
              />
            </div>

            <h1 className="mt-8 text-[22px] font-semibold leading-snug text-ink sm:text-[26px]">
              {queue[position].question_text}
            </h1>

            <ul className="mt-6 space-y-3">
              {queue[position].options.map((option, index) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => answer(index)}
                    className="group flex min-h-16 w-full items-center gap-3.5 rounded-2xl border-2
                               border-line bg-surface px-4 py-3 text-left text-[18px]
                               text-ink shadow-soft transition-all hover:border-action
                               active:scale-[0.98] active:bg-brand-fill"
                  >
                    <span
                      className="flex size-9 shrink-0 items-center justify-center rounded-full
                                 bg-sunken text-sm font-bold text-ink-muted transition-colors
                                 group-hover:bg-action group-hover:text-action-ink"
                    >
                      {String.fromCharCode(65 + index)}
                    </span>
                    <span className="min-w-0">{option}</span>
                  </button>
                </li>
              ))}
            </ul>

            {/* No "back" and no "skip": a child correcting an earlier answer
                after seeing a later question is a different measurement, and
                there is no teacher watching the screen to adjudicate. */}
            <p className="mt-8 text-sm text-ink-muted">
              Choose the answer you think is right. You won’t be told whether it was correct.
            </p>
          </>
        )}

        {phase === "handback" && learner && (
          <div className="py-16 text-center">
            {/* A thank-you, not a score: the learner is never told how they did. */}
            <span className="mx-auto mb-6 flex size-24 items-center justify-center rounded-full bg-brand-fill text-brand-strong">
              <Icon name="check" className="size-12" strokeWidth={2.2} />
            </span>
            <h1 className="text-[28px] font-bold tracking-tight text-ink">
              {/* A name may already end in a full stop: "Amina W." */}
              Finished, {learner.name.replace(/\.$/, "")}.
            </h1>
            <p className="mt-2 flex items-center justify-center gap-2 text-[17px] text-ink-muted">
              <Icon name="hand" className="size-5" />
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
          <form
            onSubmit={unlock}
            className="mx-auto max-w-sm rounded-3xl border border-line bg-surface p-6 shadow-lift sm:mt-10"
          >
            <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-brand-fill text-brand-strong">
              <Icon name="lock" className="size-6" />
            </span>
            <h1 className="text-xl font-bold text-ink">Leave quiz mode</h1>
            <p className="mt-1 text-[15px] text-ink-muted">
              {usePassword
                ? `Enter the password for ${profile?.email ?? "your account"}.`
                : "Enter the PIN you chose when you started this quiz."}
            </p>

            <div className="mt-4">
              {usePassword ? (
                <Field
                  label="Password"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              ) : (
                <Field
                  label="PIN"
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={4}
                  required
                  value={attempt}
                  onChange={(e) => setAttempt(e.target.value.replace(/\D/g, "").slice(0, 4))}
                />
              )}
            </div>

            <div className="mt-4">
              <Note tone="error">{error}</Note>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              <Button type="submit" disabled={busy}>
                {busy ? "Checking…" : "Unlock"}
              </Button>
              <Button type="button" variant="secondary" onClick={backToQuiz}>
                Back to the quiz
              </Button>
            </div>

            {!usePassword && profile?.has_password && (
              <Button
                type="button"
                variant="ghost"
                className="-ml-3 mt-4"
                onClick={() => {
                  setUsePassword(true);
                  setError(null);
                }}
              >
                Forgot the PIN? Use your password
              </Button>
            )}

            {answers.length > 0 && (
              <div className="mt-6">
                <Note tone="warn">
                  {answers.length === 1 ? "1 answer is" : `${answers.length} answers are`} not
                  saved yet. Go back to the quiz and end the session to keep{" "}
                  {answers.length === 1 ? "it" : "them"}.
                </Note>
              </div>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
