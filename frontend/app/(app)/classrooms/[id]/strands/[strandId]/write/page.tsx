"use client";

/**
 * A teacher writes a question of their own for a strand (24 October).
 *
 * The question bank could always take one - the API has accepted a
 * teacher's question since Phase 2 - but the only way to add questions on a
 * phone was to have the AI write them. A strand that is not linked to the
 * curriculum catalogue had no way to get questions at all.
 *
 * A page of its own rather than a form on the strand page: on a phone the
 * strand page is already a long list, and a half-written question should
 * not sit between the review card and the approved questions.
 *
 * After saving, the question is shown as learners' teachers will see it,
 * with a way to write another - teachers tend to write several at once.
 */

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { strandTitle } from "@/components/ClassStrands";
import { QuestionView, QuestionWriter } from "@/components/Question";
import { Button, ButtonLink, Card, Loading, Note, PageHeader } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { Item, Strand } from "@/lib/types";

export default function WriteQuestionPage() {
  const { id: classId, strandId } = useParams<{ id: string; strandId: string }>();
  const [strand, setStrand] = useState<Strand | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Item[]>([]);
  // A new key gives a fresh, empty form after "Write another".
  const [formKey, setFormKey] = useState(0);
  const [writing, setWriting] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Strand[]>(`/api/classrooms/${classId}/strands`)
      .then((strands) => {
        if (cancelled) return;
        const found = strands.find((s) => s.strand_id === strandId) ?? null;
        setStrand(found);
        if (!found) setError("This class isn’t assessed on that strand.");
      })
      .catch((e) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "No such class at your school."
            : errorMessage(e, "Could not load the strand"),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [classId, strandId]);

  const back = `/classrooms/${classId}/strands/${strandId}`;
  const [title, context] = strand ? strandTitle(strand.name) : ["Write a question", ""];
  const last = saved.at(-1);

  return (
    <>
      <PageHeader
        back={{ href: back, label: "Questions" }}
        title="Write a question"
        description={strand ? [title, context].filter(Boolean).join(" · ") : undefined}
      />

      <Note tone="error">{error}</Note>
      {!strand && !error && <Loading what="the strand" />}

      {strand && (
        <div className="space-y-6">
          {last && !writing && (
            <Card className="p-4">
              <Note tone="ok">
                Saved. {saved.length > 1 ? `${saved.length} questions written. ` : ""}
                It’s approved and can be used in the next quiz.
              </Note>
              <div className="mt-4">
                <QuestionView item={last} />
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <Button
                  onClick={() => {
                    setFormKey((k) => k + 1);
                    setWriting(true);
                  }}
                >
                  Write another
                </Button>
                <ButtonLink href={back}>Back to the questions</ButtonLink>
              </div>
            </Card>
          )}

          {writing && (
            <Card className="p-4">
              <QuestionWriter
                key={formKey}
                strandId={strandId}
                onSaved={(item) => {
                  setSaved((s) => [...s, item]);
                  setWriting(false);
                  window.scrollTo({ top: 0 });
                }}
              />
            </Card>
          )}
        </div>
      )}
    </>
  );
}
