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

export function QuestionView({
  item,
  showQuestion = true,
}: {
  item: Item;
  /** False where the question is already shown, as in an opened list row. */
  showQuestion?: boolean;
}) {
  const options = item.options ?? [];
  return (
    <div>
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
                className={`rounded-md border px-3 py-2.5 ${
                  isKey ? "border-ok/40 bg-ok-fill" : "border-line bg-surface"
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className="w-5 shrink-0 font-semibold text-ink-muted">{LETTERS[n]}</span>
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
        <blockquote className="mt-3 border-l-2 border-line-strong pl-3 text-sm text-ink-muted">
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
          className="mt-1 block w-full rounded-md border border-line-strong bg-surface px-3 py-2
                     text-base text-ink"
        />
      </label>

      {hasOptions && (
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium text-ink">
            Options — choose the correct one
          </legend>
          {options.map((option, n) => (
            <div key={n} className="rounded-md border border-line p-3">
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
                      className="mt-1.5 block w-full rounded-md border border-line-strong
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
          className="mt-1 block w-full rounded-md border border-line-strong bg-surface px-3 py-2
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
