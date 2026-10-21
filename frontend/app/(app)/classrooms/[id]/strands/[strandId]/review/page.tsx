"use client";

/**
 * Reviewing AI-written drafts, one at a time.
 *
 * One card per screen, on purpose: a list invites approving ten questions
 * without reading them, and a question with a wrong key, approved, goes
 * into learners' levels. The card shows what a judgement needs - the key,
 * why it is right, what each wrong option suggests, and the curriculum line
 * it was written from - and three decisions:
 *
 *   - Approve: it can be given to learners from now on
 *   - Edit: fix the wording, an option, the key or the mark scheme; it stays
 *     a draft until approved
 *   - Reject: never used. Kept, not deleted, because how often teachers
 *     approve what the AI writes is measured
 *
 * "Later" moves on without deciding. Rejecting asks once, since it cannot be
 * undone from here.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { QuestionEditor, QuestionView } from "@/components/Question";
import { Button, ButtonLink, Card, Empty, Loading, Note, PageHeader } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Item } from "@/lib/types";

export default function ReviewPage() {
  const { id: classId, strandId } = useParams<{ id: string; strandId: string }>();
  const back = `/classrooms/${classId}/strands/${strandId}`;

  const [drafts, setDrafts] = useState<Item[] | null>(null);
  const [position, setPosition] = useState(0);
  const [mode, setMode] = useState<"view" | "edit" | "confirm-reject">("view");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState({ approved: 0, rejected: 0 });

  const load = useCallback(
    () => api.get<Item[]>(`/api/items?strand_id=${strandId}&status=draft`),
    [strandId],
  );

  useEffect(() => {
    let cancelled = false;
    load()
      .then((list) => !cancelled && setDrafts(list))
      .catch((e) => !cancelled && setError(errorMessage(e, "Could not load the drafts")));
    return () => {
      cancelled = true;
    };
  }, [load]);

  const current = drafts && drafts.length > 0 ? drafts[position % drafts.length] : null;

  /** Take the current draft out of the queue and stay at the same place. */
  function settle(outcome: "approved" | "rejected") {
    if (!drafts || !current) return;
    const next = drafts.filter((d) => d.item_id !== current.item_id);
    setDecided((d) => ({ ...d, [outcome]: d[outcome] + 1 }));
    setDrafts(next);
    setPosition((p) => (next.length === 0 ? 0 : p % next.length));
    setMode("view");
  }

  async function decide(action: "approve" | "reject") {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/items/${current.item_id}/${action}`);
      settle(action === "approve" ? "approved" : "rejected");
    } catch (e) {
      setError(errorMessage(e, `Could not ${action} the question`));
    } finally {
      setBusy(false);
    }
  }

  function saved(updated: Item) {
    setDrafts((list) => list?.map((d) => (d.item_id === current?.item_id ? updated : d)) ?? null);
    setMode("view");
  }

  const remaining = drafts?.length ?? 0;

  return (
    <>
      <PageHeader
        back={{ href: back, label: "Questions" }}
        title="Review questions"
        description={
          drafts === null
            ? undefined
            : remaining === 0
              ? "Nothing left to review."
              : `Question ${(position % remaining) + 1} of ${remaining} waiting`
        }
      />

      <Note tone="error">{error}</Note>
      {drafts === null && !error && <Loading what="the drafts" />}

      {drafts !== null && remaining === 0 && (
        <Empty
          title="All reviewed"
          action={
            <ButtonLink href={back} variant="primary">
              Back to questions
            </ButtonLink>
          }
        >
          {decided.approved + decided.rejected > 0
            ? `You approved ${decided.approved} and rejected ${decided.rejected}. ` +
              "Approved questions can now be given in a quiz."
            : "There are no drafts waiting for this strand."}
        </Empty>
      )}

      {current && (
        <Card className="p-4">
          {mode === "edit" ? (
            <QuestionEditor item={current} onSaved={saved} onCancel={() => setMode("view")} />
          ) : (
            <>
              <QuestionView item={current} />

              {mode === "confirm-reject" ? (
                <div role="alertdialog" aria-label="Reject this question" className="mt-5 rounded-md bg-risk-fill p-3">
                  <p className="text-[15px] text-ink">
                    Reject this question? It will never be given to learners.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button variant="danger" disabled={busy} onClick={() => decide("reject")}>
                      {busy ? "Rejecting…" : "Reject"}
                    </Button>
                    <Button variant="secondary" disabled={busy} onClick={() => setMode("view")}>
                      Keep reviewing
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-5 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                  <Button
                    className="col-span-2"
                    disabled={busy}
                    onClick={() => decide("approve")}
                  >
                    {busy ? "Saving…" : "Approve"}
                  </Button>
                  <Button variant="secondary" disabled={busy} onClick={() => setMode("edit")}>
                    Edit
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() => setMode("confirm-reject")}
                  >
                    Reject
                  </Button>
                  {remaining > 1 && (
                    <Button
                      variant="ghost"
                      className="col-span-2"
                      disabled={busy}
                      onClick={() => setPosition((p) => p + 1)}
                    >
                      Later
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
        </Card>
      )}
    </>
  );
}
