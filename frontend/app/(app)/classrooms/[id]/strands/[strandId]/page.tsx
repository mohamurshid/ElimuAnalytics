"use client";

/**
 * One strand's questions: how many, writing more, reviewing, reporting.
 *
 * Reached from the class page's strand row. Everything about a strand's
 * question bank is here rather than spread over the class page, which on a
 * phone is already long.
 *
 *   - Review comes first when there is anything to review: drafts are
 *     waiting on this teacher, and nothing the AI wrote is used until a
 *     teacher approves it.
 *   - Writing more shows what is left of the school's daily allowance, and
 *     keeps watching a run that is still being written if the page is
 *     reloaded - a run takes about forty seconds.
 *   - The approved questions, each with Report. A report takes a question
 *     out of new quizzes and out of learners' levels at once, until a head
 *     teacher looks at it.
 *   - For a head teacher, the reported questions: keep, edit or retire.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { strandTitle } from "@/components/ClassStrands";
import { QuestionEditor, QuestionView } from "@/components/Question";
import { Badge, Button, ButtonLink, Card, Loading, Note, PageHeader } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { GenerationRun, Item, Strand, StrandGeneration } from "@/lib/types";

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export default function StrandPage() {
  const { id: classId, strandId } = useParams<{ id: string; strandId: string }>();
  const { profile } = useAuth();
  const isHead = profile?.role !== "teacher";

  const [strand, setStrand] = useState<Strand | null>(null);
  const [items, setItems] = useState<Item[] | null>(null);
  const [generation, setGeneration] = useState<StrandGeneration | null>(null);
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writing, setWriting] = useState(false);
  const polling = useRef(false);

  const load = useCallback(async () => {
    const [strands, list, gen] = await Promise.all([
      api.get<Strand[]>(`/api/classrooms/${classId}/strands`),
      api.get<Item[]>(`/api/items?strand_id=${strandId}&status=approved&status=reported`),
      api.get<StrandGeneration>(`/api/strands/${strandId}/generation`),
    ]);
    setStrand(strands.find((s) => s.strand_id === strandId) ?? null);
    setItems(list);
    setGeneration(gen);
    return gen;
  }, [classId, strandId]);

  /** Poll a run until it is no longer pending, then refresh the counts. */
  const follow = useCallback(
    async (runId: string) => {
      if (polling.current) return;
      polling.current = true;
      setWriting(true);
      try {
        for (;;) {
          const next = await api.get<GenerationRun>(`/api/generation-runs/${runId}`);
          setRun(next);
          if (next.status !== "pending") break;
          await new Promise((r) => setTimeout(r, 3000));
        }
        await load();
      } catch (e) {
        setError(errorMessage(e, "Lost track of the questions being written"));
      } finally {
        polling.current = false;
        setWriting(false);
      }
    },
    [load],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const gen = await load();
        if (cancelled) return;
        // Only a run still being written is picked up. A finished one from an
        // earlier visit is not reported again: "5 written, waiting for review"
        // goes stale the moment those drafts are reviewed.
        if (gen.running) void follow(gen.running.run_id);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof ApiError && e.status === 404
              ? "This strand isn’t used by a class at your school."
              : errorMessage(e, "Could not load the strand"),
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [load, follow]);

  async function write() {
    setError(null);
    try {
      const started = await api.post<GenerationRun>(`/api/strands/${strandId}/generate`, {});
      setRun(started);
      void follow(started.run_id);
    } catch (e) {
      setError(errorMessage(e, "Could not start writing questions"));
    }
  }

  const [title, context] = strand ? strandTitle(strand.name) : ["Questions", ""];
  const approved = items?.filter((i) => i.status === "approved") ?? [];
  const reported = items?.filter((i) => i.status === "reported") ?? [];
  const drafts = strand?.draft_items ?? 0;

  return (
    <>
      <PageHeader
        back={{ href: `/classrooms/${classId}`, label: "Class" }}
        title={title}
        description={[context, strand?.grade, strand?.learning_area].filter(Boolean).join(" · ")}
      />

      <Note tone="error">{error}</Note>
      {!items && !error && <Loading what="the questions" />}

      {strand && items && (
        <div className="space-y-6">
          <div className="flex flex-wrap gap-1.5">
            <Badge>{plural(approved.length, "approved question", "approved questions")}</Badge>
            {drafts > 0 && <Badge tone="warn">{drafts} waiting for review</Badge>}
            {reported.length > 0 && <Badge tone="risk">{reported.length} reported</Badge>}
          </div>

          {drafts > 0 && (
            <Card className="p-4">
              <h2 className="text-base font-semibold text-ink">
                {plural(drafts, "question is", "questions are")} waiting for review
              </h2>
              <p className="mt-1 text-sm text-ink-muted">
                Written by AI. None is given to learners until a teacher approves it.
              </p>
              <ButtonLink
                href={`/classrooms/${classId}/strands/${strandId}/review`}
                variant="primary"
                className="mt-4"
              >
                Review questions
              </ButtonLink>
            </Card>
          )}

          <WriteCard
            strand={strand}
            generation={generation}
            run={run}
            writing={writing}
            onWrite={write}
          />

          {isHead && reported.length > 0 && (
            <section aria-labelledby="reported-heading">
              <h2 id="reported-heading" className="mb-3 text-lg font-semibold text-ink">
                Reported questions
              </h2>
              <p className="mb-3 text-sm text-ink-muted">
                Out of quizzes and levels until you decide. Keeping one puts it back;
                retiring keeps its answers but stops it counting for good.
              </p>
              <div className="space-y-3">
                {reported.map((item) => (
                  <ReportedQuestion key={item.item_id} item={item} onChange={load} />
                ))}
              </div>
            </section>
          )}

          <section aria-labelledby="approved-heading">
            <h2 id="approved-heading" className="mb-3 text-lg font-semibold text-ink">
              Approved questions
            </h2>
            {approved.length === 0 ? (
              <Card className="p-4 text-sm text-ink-muted">
                None yet. Write some, then review them.
              </Card>
            ) : (
              <Card>
                <ul className="divide-y divide-line">
                  {approved.map((item) => (
                    <ApprovedQuestion key={item.item_id} item={item} onChange={load} />
                  ))}
                </ul>
              </Card>
            )}
          </section>
        </div>
      )}
    </>
  );
}

function WriteCard({
  strand,
  generation,
  run,
  writing,
  onWrite,
}: {
  strand: Strand;
  generation: StrandGeneration | null;
  run: GenerationRun | null;
  writing: boolean;
  onWrite: () => void;
}) {
  const left = generation?.remaining_today ?? 0;
  const per = generation?.per_run ?? 5;
  const linked = Boolean(strand.curriculum_key);

  return (
    <Card className="p-4">
      <h2 className="text-base font-semibold text-ink">Write more questions</h2>
      {!linked ? (
        <p className="mt-1 text-sm text-ink-muted">
          This strand isn’t linked to the curriculum catalogue, so there is no curriculum
          text to write from.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-ink-muted">
            AI writes {per} questions from this sub-strand’s KICD curriculum. You review
            each one before it is used. Your school has {plural(left, "request", "requests")}{" "}
            left today.
          </p>
          <Button
            variant="secondary"
            className="mt-4"
            disabled={writing || left === 0}
            onClick={onWrite}
          >
            {writing ? "Writing… about 40 seconds" : `Write ${per} questions`}
          </Button>
        </>
      )}

      {run && run.status === "ready" && !writing && (
        <div className="mt-4">
          <Note tone="ok">
            {run.produced > 0
              ? `${plural(run.produced, "question was", "questions were")} written and ` +
                "are waiting for review."
              : "No questions passed the checks this time."}
            {run.dropped.length > 0 &&
              ` ${plural(run.dropped.length, "question was", "questions were")} left out ` +
                "because they failed a check."}
          </Note>
        </div>
      )}
      {run && run.status === "failed" && !writing && (
        <div className="mt-4">
          <Note tone="error">{run.error}</Note>
        </div>
      )}
    </Card>
  );
}

function ApprovedQuestion({ item, onChange }: { item: Item; onChange: () => Promise<unknown> }) {
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function report(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/items/${item.item_id}/report`, { reason: reason.trim() });
      await onChange();
    } catch (err) {
      setError(errorMessage(err, "Could not report the question"));
      setBusy(false);
    }
  }

  return (
    <li>
      <details className="group">
        <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-3">
          <span className="min-w-0 flex-1 text-[15px] text-ink">{item.question_text}</span>
          <span aria-hidden className="text-ink-subtle transition group-open:rotate-90">
            ›
          </span>
        </summary>
        <div className="border-t border-line px-4 py-4">
          <QuestionView item={item} showQuestion={false} />
          {!reporting ? (
            <Button variant="ghost" size="sm" className="mt-3 -ml-3" onClick={() => setReporting(true)}>
              Report a problem
            </Button>
          ) : (
            <form onSubmit={report} className="mt-4 space-y-3 rounded-md bg-sunken p-3">
              <label className="block">
                <span className="text-sm font-medium text-ink">What is wrong with it?</span>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  required
                  minLength={5}
                  placeholder="For example: option B is also correct"
                  className="mt-1 block w-full rounded-md border border-line-strong bg-surface
                             px-3 py-2 text-base text-ink"
                />
              </label>
              <p className="text-sm text-ink-muted">
                It leaves quizzes and stops counting toward levels until a head teacher
                reviews it. Answers already given are kept.
              </p>
              <Note tone="error">{error}</Note>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" variant="danger" disabled={busy}>
                  {busy ? "Reporting…" : "Report question"}
                </Button>
                <Button type="button" variant="secondary" onClick={() => setReporting(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </div>
      </details>
    </li>
  );
}

function ReportedQuestion({ item, onChange }: { item: Item; onChange: () => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "approve" | "retire") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/items/${item.item_id}/${action}`);
      await onChange();
    } catch (e) {
      setError(errorMessage(e, "Could not update the question"));
      setBusy(false);
    }
  }

  return (
    <Card className="p-4">
      <Note tone="warn">Reported: {item.report_reason}</Note>
      <div className="mt-3">
        {editing ? (
          <QuestionEditor
            item={item}
            onSaved={() => void onChange()}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <QuestionView item={item} />
        )}
      </div>
      <Note tone="error">{error}</Note>
      {!editing && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => act("approve")}>
            Keep it
          </Button>
          <Button variant="secondary" disabled={busy} onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button variant="danger" disabled={busy} onClick={() => act("retire")}>
            Retire
          </Button>
        </div>
      )}
    </Card>
  );
}
