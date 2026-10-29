"use client";

/**
 * A question as a TEACHER sees it: the key marked, why it is right, what
 * each wrong option suggests, and the curriculum line it was written from.
 *
 * Never rendered on a screen a learner holds. The device quiz has its own
 * view built from QuizItem, which carries none of this - the server never
 * sends it there.
 *
 * The key is marked with a word as well as a tick, and wrong options with
 * what choosing them suggests rather than a cross: the point of a review is
 * to judge the reasoning, not to see a colour.
 */

import { useState } from "react";

import { Badge, Button, Field, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Item } from "@/lib/types";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

/**
 * Is the key clearly the longest option? A known giveaway: learners learn
 * that the careful, qualified answer is usually the right one. Measured 21
 * October: the key was the longest option in about a third of generated
 * questions, against about a quarter by chance (run 20261021_095316).
 *
 * "Clearly" is a judgement, not a measurement: at least a quarter longer and
 * five characters longer than the next longest, so a one-word difference is
 * not flagged.
 */
export function keyStandsOutByLength(
  item: Pick<Item, "options" | "correct_option">,
): boolean {
  const options = item.options ?? [];
  const key = item.correct_option;
  if (key === null || options.length < 2 || !options[key]) return false;
  const others = Math.max(...options.filter((_, n) => n !== key).map((o) => o.length));
  const mine = options[key].length;
  return mine >= others * 1.25 && mine - others >= 5;
}

export function QuestionView({
  item,
  showQuestion = true,
  hints = false,
}: {
  item: Item;
  /** False where the question is already shown, as in an opened list row. */
  showQuestion?: boolean;
  /** Point out item-writing flaws - where the question can still be edited. */
  hints?: boolean;
}) {
  const options = item.options ?? [];
  return (
    <div>
      {hints && keyStandsOutByLength(item) && (
        <div className="mb-4">
          <Note tone="warn">
            The correct answer is much longer than the others, which can give it away.
            Consider evening out the lengths with Edit.
          </Note>
        </div>
      )}
      {showQuestion && (
        <p className="mb-4 text-lg font-medium leading-snug text-ink">{item.question_text}</p>
      )}

      {options.length > 0 ? (
        <ol className="space-y-2">
          {options.map((option, n) => {
            const isKey = n === item.correct_option;
            const misconception = item.misconceptions?.[n];
            return (
              <li
                key={n}
                className={`rounded-xl border px-3 py-2.5 ${
                  isKey ? "border-ok/40 bg-ok-fill" : "border-line bg-surface"
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-bold text-ink-muted">
                    {LETTERS[n]}
                  </span>
                  <span className="min-w-0 flex-1 text-[15px] text-ink">{option}</span>
                  {isKey && <Badge tone="ok">✓ Correct</Badge>}
                </div>
                {!isKey && misconception && (
                  <p className="mt-1 pl-7 text-sm text-ink-muted">
                    <span className="font-medium">If chosen:</span> {misconception}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-sm text-ink-muted">
          No options — a question the teacher reads out and marks by hand.
        </p>
      )}

      {item.rationale && (
        <p className="mt-4 text-[15px] text-ink">
          <span className="font-semibold">Why it’s right:</span> {item.rationale}
        </p>
      )}

      {item.curriculum_excerpt && (
        <blockquote className="mt-3 rounded-r-xl border-l-4 border-brand-strong/40 bg-brand-fill/50 py-2 pl-3 pr-3 text-sm text-ink-muted">
          <span className="font-medium text-ink">From the curriculum:</span> “
          {item.curriculum_excerpt}”
        </blockquote>
      )}

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge>{item.source === "ai" ? "Written by AI" : "Written by a teacher"}</Badge>
        {item.version > 1 && <Badge>Version {item.version}</Badge>}
        {item.response_count > 0 && (
          <Badge>
            {item.response_count} {item.response_count === 1 ? "answer" : "answers"}
          </Badge>
        )}
      </div>
    </div>
  );
}

/**
 * Edit a question's wording, options, key and mark scheme. The server
 * decides what saving means: in place for an unanswered question, a new
 * version for an answered one (head teacher only). `onSaved` receives the
 * question as it now stands - its id is new if a version was made.
 */
export function QuestionEditor({
  item,
  onSaved,
  onCancel,
}: {
  item: Item;
  onSaved: (saved: Item) => void;
  onCancel: () => void;
}) {
  const hasOptions = (item.options ?? []).length > 0;
  const [text, setText] = useState(item.question_text);
  const [options, setOptions] = useState<string[]>(item.options ?? []);
  const [key, setKey] = useState<number>(item.correct_option ?? 0);
  const [misconceptions, setMisconceptions] = useState<string[]>(
    (item.options ?? []).map((_, n) => item.misconceptions?.[n] ?? ""),
  );
  const [rationale, setRationale] = useState(item.rationale ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = hasOptions
        ? {
            question_text: text.trim(),
            options: options.map((o) => o.trim()),
            correct_option: key,
            misconceptions: misconceptions.map((m, n) => (n === key || !m.trim() ? null : m.trim())),
            rationale: rationale.trim() || null,
          }
        : { question_text: text.trim(), rationale: rationale.trim() || null };
      onSaved(await api.patch<Item>(`/api/items/${item.item_id}`, body));
    } catch (err) {
      setError(errorMessage(err, "Could not save the question"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <label className="block">
        <span className="text-sm font-medium text-ink">Question</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          required
          className="mt-1 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2
                     text-base text-ink"
        />
      </label>

      {hasOptions && (
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium text-ink">
            Options — choose the correct one
          </legend>
          {options.map((option, n) => (
            <div key={n} className="rounded-xl border border-line p-3">
              <div className="flex items-end gap-3">
                <input
                  type="radio"
                  name="key"
                  checked={key === n}
                  onChange={() => setKey(n)}
                  aria-label={`Option ${LETTERS[n]} is correct`}
                  className="mb-3 size-5 shrink-0"
                />
                <div className="min-w-0 flex-1">
                  <Field
                    label={`Option ${LETTERS[n]}`}
                    value={option}
                    required
                    onChange={(e) =>
                      setOptions((o) => o.map((x, i) => (i === n ? e.target.value : x)))
                    }
                  />
                </div>
              </div>
              {key !== n && (
                <div className="mt-2 pl-7">
                  {/* A textarea, not a one-line input: these are sentences, and a
                      one-line box on a phone shows the first few words. */}
                  <label className="block">
                    <span className="text-sm font-medium text-ink">
                      If chosen, the learner may believe…
                    </span>
                    <textarea
                      value={misconceptions[n] ?? ""}
                      required
                      rows={2}
                      onChange={(e) =>
                        setMisconceptions((m) => m.map((x, i) => (i === n ? e.target.value : x)))
                      }
                      className="mt-1.5 block w-full rounded-xl border border-line-strong
                                 bg-surface px-3 py-2 text-base text-ink"
                    />
                  </label>
                </div>
              )}
            </div>
          ))}
        </fieldset>
      )}

      <label className="block">
        <span className="text-sm font-medium text-ink">Why the correct answer is right</span>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={2}
          className="mt-1 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2
                     text-base text-ink"
        />
      </label>

      {item.response_count > 0 && (
        <Note tone="warn">
          Learners have answered this question, so saving makes a new version. The old
          one is kept with their answers but stops counting.
        </Note>
      )}
      <Note tone="error">{error}</Note>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/**
 * Write a new question from scratch (24 October).
 *
 * The teacher's own question is approved as soon as it is saved - its author
 * is its reviewer, as agreed on 20 October - so it can go into the next quiz.
 *
 * Options and the key are required; the note on each wrong option and the
 * reason the key is right are not (agreed 24 October). They are what makes a
 * wrong answer diagnostic, but asking for three sentences on a phone is what
 * would stop a teacher writing questions at all. The AI's questions and any
 * edit of an existing one still carry them.
 */
const START_OPTIONS = 4;

export function QuestionWriter({
  strandId,
  onSaved,
}: {
  strandId: string;
  onSaved: (saved: Item) => void;
}) {
  const [text, setText] = useState("");
  const [options, setOptions] = useState<string[]>(Array(START_OPTIONS).fill(""));
  const [notes, setNotes] = useState<string[]>(Array(START_OPTIONS).fill(""));
  const [key, setKey] = useState<number | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addOption() {
    if (options.length >= LETTERS.length) return;
    setOptions((o) => [...o, ""]);
    setNotes((m) => [...m, ""]);
  }

  function removeOption(n: number) {
    if (options.length <= 2) return;
    setOptions((o) => o.filter((_, i) => i !== n));
    setNotes((m) => m.filter((_, i) => i !== n));
    setKey((k) => (k === null || k === n ? null : k > n ? k - 1 : k));
  }

  /** What stops it being saved, in the teacher's words - or null. */
  function problem(): string | null {
    const cleaned = options.map((o) => o.trim());
    if (text.trim().length < 5) return "Write the question first.";
    if (cleaned.some((o) => !o)) return "Fill in every option, or remove the empty one.";
    // Same rule as the server (item_status._option_key): a capital at the
    // start of a word is ignored, capitals inside one are kept, so the
    // word-stress options "con-FLICT" and "CON-flict" stay different.
    const optionKey = (o: string) =>
      o.split(/\s+/).join(" ").replace(/\b(\w)/g, (c) => c.toLowerCase());
    if (new Set(cleaned.map(optionKey)).size !== cleaned.length)
      return "Two options are the same.";
    if (key === null) return "Choose which option is correct.";
    return null;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const why = problem();
    if (why) {
      setError(why);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const misconceptions = notes.map((m, n) => (n === key || !m.trim() ? null : m.trim()));
      onSaved(
        await api.post<Item>("/api/items", {
          strand_id: strandId,
          question_text: text.trim(),
          options: options.map((o) => o.trim()),
          correct_option: key,
          misconceptions: misconceptions.some(Boolean) ? misconceptions : null,
          rationale: rationale.trim() || null,
        }),
      );
    } catch (err) {
      setError(errorMessage(err, "Could not save the question"));
    } finally {
      setBusy(false);
    }
  }

  const longKey =
    key !== null &&
    options.every((o) => o.trim()) &&
    keyStandsOutByLength({ options, correct_option: key });

  return (
    <form onSubmit={save} className="space-y-5" noValidate>
      <label className="block">
        <span className="text-sm font-medium text-ink">Question</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          placeholder="For example: Which of these materials is the best conductor of heat?"
          className="mt-1.5 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2
                     text-base text-ink placeholder:text-ink-subtle"
        />
      </label>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-ink">
          Options — tap the circle beside the correct one
        </legend>
        {options.map((option, n) => (
          <div
            key={n}
            className={`rounded-xl border p-3 ${
              key === n ? "border-ok/40 bg-ok-fill" : "border-line bg-surface"
            }`}
          >
            <div className="flex items-center gap-3">
              <input
                type="radio"
                name="key"
                checked={key === n}
                onChange={() => setKey(n)}
                aria-label={`Option ${LETTERS[n]} is correct`}
                className="size-5 shrink-0"
              />
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-sunken text-xs font-bold text-ink-muted">
                {LETTERS[n]}
              </span>
              <input
                value={option}
                onChange={(e) =>
                  setOptions((o) => o.map((x, i) => (i === n ? e.target.value : x)))
                }
                aria-label={`Option ${LETTERS[n]}`}
                className="block min-h-11 min-w-0 flex-1 rounded-xl border border-line-strong
                           bg-surface px-3 text-base text-ink"
              />
              {options.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeOption(n)}
                  aria-label={`Remove option ${LETTERS[n]}`}
                  className="flex size-11 shrink-0 items-center justify-center rounded-xl
                             text-xl text-ink-subtle hover:bg-sunken hover:text-ink"
                >
                  ×
                </button>
              )}
            </div>
            {key === n ? (
              <p className="mt-2 pl-8 text-sm font-medium text-ok">✓ Correct answer</p>
            ) : (
              key !== null && (
                <label className="mt-2 block pl-8">
                  <span className="text-sm text-ink-muted">
                    If chosen, the learner may believe… (optional)
                  </span>
                  <textarea
                    aria-label={`Option ${LETTERS[n]}: if chosen, the learner may believe (optional)`}
                    value={notes[n] ?? ""}
                    rows={2}
                    onChange={(e) =>
                      setNotes((m) => m.map((x, i) => (i === n ? e.target.value : x)))
                    }
                    className="mt-1 block w-full rounded-xl border border-line-strong bg-surface
                               px-3 py-2 text-base text-ink"
                  />
                </label>
              )
            )}
          </div>
        ))}
        {options.length < LETTERS.length && (
          <Button type="button" variant="ghost" size="md" className="-ml-3" onClick={addOption}>
            + Add an option
          </Button>
        )}
      </fieldset>

      {longKey && (
        <Note tone="warn">
          The correct answer is much longer than the others, which can give it away.
        </Note>
      )}

      <label className="block">
        <span className="text-sm font-medium text-ink">
          Why the correct answer is right (optional)
        </span>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          rows={2}
          className="mt-1.5 block w-full rounded-xl border border-line-strong bg-surface px-3 py-2
                     text-base text-ink"
        />
      </label>

      <p className="text-sm text-ink-muted">
        Your question is approved as soon as you save it, so it can be used in the next
        quiz. Learners never see which answer is correct or your notes.
      </p>
      <Note tone="error">{error}</Note>

      <Button type="submit" disabled={busy} className="w-full sm:w-auto">
        {busy ? "Saving…" : "Save question"}
      </Button>
    </form>
  );
}
