"use client";

/**
 * How many questions a quiz has: 5, 10, 15, or every approved question.
 *
 * The teacher picks the length; the server picks which questions - spread
 * from easy to hard, favouring ones few learners have answered - and saves
 * the choice, so the whole class gets the same set.
 */

export type QuizLength = 5 | 10 | 15 | null;

const CHOICES: { value: QuizLength; label: string }[] = [
  { value: 5, label: "5" },
  { value: 10, label: "10" },
  { value: 15, label: "15" },
  { value: null, label: "All" },
];

export function QuizLengthPicker({
  value,
  onChange,
  available,
}: {
  value: QuizLength;
  onChange: (next: QuizLength) => void;
  /** Approved questions in the strand; longer choices than this are the same as All. */
  available?: number;
}) {
  return (
    <div>
      <span className="text-sm font-medium text-ink">Questions</span>
      <div
        role="radiogroup"
        aria-label="Number of questions"
        className="mt-1 grid grid-cols-4 gap-1 rounded-md border border-line-strong bg-surface p-1"
      >
        {CHOICES.map((choice) => {
          const pointless =
            choice.value !== null && available !== undefined && choice.value >= available;
          return (
            <button
              key={choice.label}
              type="button"
              role="radio"
              aria-checked={value === choice.value}
              disabled={pointless}
              onClick={() => onChange(choice.value)}
              className={`min-h-10 min-w-12 rounded px-2 text-[15px] font-medium
                          disabled:cursor-not-allowed disabled:text-ink-subtle disabled:opacity-50
                          ${value === choice.value
                            ? "bg-sunken text-ink"
                            : "text-ink-muted hover:text-ink"}`}
            >
              {choice.label}
            </button>
          );
        })}
      </div>
      {available !== undefined && (
        <p className="mt-1 text-xs text-ink-subtle">
          {available} approved {available === 1 ? "question" : "questions"} in this strand
        </p>
      )}
    </div>
  );
}
