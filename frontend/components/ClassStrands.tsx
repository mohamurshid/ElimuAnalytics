"use client";

/**
 * What a class is assessed on, on the class page.
 *
 * Each row leads with the sub-strand, because that is what a teacher picked
 * and what a quiz covers; the strand and learning area sit underneath as
 * context. A strand from another grade carries its grade, so revision of an
 * earlier year's work is visible as a choice rather than looking like a
 * mistake.
 *
 * Removing asks first, and says what it does and does not do: it takes the
 * strand off this class, and keeps every answer. That sentence is the whole
 * reason removal is safe, so it is shown at the moment it matters.
 */

import { useState } from "react";

import { Badge, Button, ButtonLink, Card, Note } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Strand } from "@/lib/types";

/** "Force and Energy / 3.2 Sound Energy" -> ["3.2 Sound Energy", "Force and Energy"]. */
export function strandTitle(name: string): [string, string] {
  const at = name.indexOf(" / ");
  return at === -1 ? [name, ""] : [name.slice(at + 3), name.slice(0, at)];
}

export function ClassStrands({
  classId,
  classGrade,
  strands,
  onChange,
}: {
  classId: string;
  classGrade: string;
  strands: Strand[];
  onChange: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove(strand: Strand) {
    setBusy(true);
    setError(null);
    try {
      await api.del(`/api/classrooms/${classId}/strands/${strand.strand_id}`);
      setConfirming(null);
      await onChange();
    } catch (e) {
      setError(errorMessage(e, "Could not remove the strand"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="strands-heading">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="strands-heading" className="text-lg font-semibold text-ink">
          What this class is assessed on
        </h2>
        <ButtonLink href={`/classrooms/${classId}/strands`} variant="secondary" size="sm">
          Add a strand
        </ButtonLink>
      </div>

      <Note tone="error">{error}</Note>

      {strands.length === 0 ? (
        <Card className="p-4">
          <p className="text-[15px] text-ink">Nothing yet.</p>
          <p className="mt-1 text-sm text-ink-muted">
            Add the sub-strands you are teaching, from the KICD curriculum for
            Grades 4–6. A quiz can then be given on each one.
          </p>
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {strands.map((strand) => {
              const [title, context] = strandTitle(strand.name);
              const asking = confirming === strand.strand_id;
              const otherGrade = strand.grade && strand.grade !== classGrade;
              return (
                <li key={strand.strand_id}>
                  <div className="flex items-start gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-[15px] font-medium text-ink">{title}</p>
                      <p className="mt-0.5 text-sm text-ink-muted">
                        {[context, strand.learning_area].filter(Boolean).join(" · ")}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {otherGrade && <Badge>{strand.grade}</Badge>}
                        {strand.active_items === 0 ? (
                          <Badge tone="warn">No questions yet</Badge>
                        ) : (
                          <Badge>
                            {strand.active_items}{" "}
                            {strand.active_items === 1 ? "question" : "questions"}
                          </Badge>
                        )}
                      </div>
                    </div>
                    {!asking && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => setConfirming(strand.strand_id)}
                        aria-label={`Remove ${title} from this class`}
                      >
                        Remove
                      </Button>
                    )}
                  </div>

                  {asking && (
                    <div
                      role="alertdialog"
                      aria-label={`Remove ${title}`}
                      className="border-t border-line bg-risk-fill px-4 py-3"
                    >
                      <p className="text-[15px] text-ink">
                        Take <strong>{title}</strong> off this class? Every answer
                        is kept, and adding it back brings the levels back.
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button variant="danger" disabled={busy} onClick={() => remove(strand)}>
                          {busy ? "Removing…" : "Remove"}
                        </Button>
                        <Button
                          variant="secondary"
                          disabled={busy}
                          onClick={() => setConfirming(null)}
                        >
                          Keep it
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </section>
  );
}
