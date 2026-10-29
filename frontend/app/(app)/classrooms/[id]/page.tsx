"use client";

/**
 * A classroom: how it is doing, and what to do next.
 *
 * It leads with the evidence rather than hiding behind the support list,
 * because that list is a conclusion and this is the evidence for it. A
 * teacher who only ever sees the list has to take the flagging on trust.
 *
 * The five actions that used to sit in one row are really three jobs, and are
 * grouped as such:
 *
 *   - Giving a quiz, two ways: on this device, or marking a paper one. As two
 *     unrelated links a teacher could not tell they were the same task.
 *   - Class records: recording levels, and recalibrating the questions. The
 *     first was called "Run assessment" and was the dominant button, which
 *     invited a teacher who wanted to quiz their class to run a statistics job
 *     instead. It is also the ONLY way a learner reaches the support list - a
 *     flag needs two consecutive low records - so it stays prominent enough
 *     to find, just not the thing pressed by mistake.
 *   - Managing learners, which is the roll.
 *
 * Below the actions, what the class is assessed on: the sub-strands picked
 * from the curriculum catalogue. Recording levels and recalibrating skip a
 * strand with no questions yet - there is nothing to estimate from, and the
 * server would refuse it.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ClassStrands } from "@/components/ClassStrands";
import { ClassSummary, Heatmap, Legend } from "@/components/Heatmap";
import { Icon, type IconName } from "@/components/Icon";
import { ButtonLink, Card, Empty, Loading, Note, PageHeader, Segmented } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { HOME } from "@/lib/routes";
import type { Assessment, Heatmap as HeatmapData } from "@/lib/types";

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export default function ClassPage() {
  const { id: classId } = useParams<{ id: string }>();

  const [data, setData] = useState<HeatmapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; link?: boolean } | null>(null);
  const [busy, setBusy] = useState<"record" | "calibrate" | null>(null);
  const [order, setOrder] = useState<"need" | "name">("need");

  const fetchHeatmap = useCallback(
    () => api.get<HeatmapData>(`/api/classrooms/${classId}/heatmap`),
    [classId],
  );

  const failure = useCallback(
    (e: unknown) =>
      e instanceof ApiError && e.status === 404
        ? "This class isn’t at your school, or it no longer exists."
        : errorMessage(e, "Could not load this class"),
    [],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await fetchHeatmap();
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(failure(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchHeatmap, failure]);

  const reload = useCallback(async () => {
    try {
      setData(await fetchHeatmap());
      setError(null);
    } catch (e) {
      setError(failure(e));
    }
  }, [fetchHeatmap, failure]);

  /** Strands with questions: the only ones there is anything to estimate from. */
  const withQuestions = data ? data.strands.filter((s) => s.active_items > 0) : [];
  // What the summary and the heatmap draw. A strand with no questions would
  // add a column of forty "no level yet" cells that say nothing the strand
  // list does not already say.
  const evidence = data ? { ...data, strands: withQuestions } : null;

  /** Re-estimate item difficulty and discrimination, then re-read. */
  async function calibrate() {
    if (!data) return;
    setError(null);
    setNotice(null);
    if (withQuestions.length === 0) {
      setNotice({
        text: "None of this class’s strands has questions yet, so there is nothing to recalibrate.",
      });
      return;
    }
    setBusy("calibrate");
    try {
      const results = await Promise.all(
        withQuestions.map((s) =>
          api.post<{ items_calibrated: number }>(`/api/strands/${s.strand_id}/calibrate`),
        ),
      );
      const items = results.reduce((n, r) => n + r.items_calibrated, 0);
      setNotice({
        text:
          `Re-checked ${plural(items, "question", "questions")} against the ` +
          "answers recorded so far. Levels below now use the updated questions.",
      });
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not recalibrate the questions"));
    } finally {
      setBusy(null);
    }
  }

  /**
   * Record an ability estimate for every learner, in every strand.
   *
   * Separate from calibration on purpose, and separate from viewing: an
   * assessment is an event in a learner's record, not a side effect of
   * opening a page. The notice says how many were saved and how many learners
   * were skipped for want of evidence, which is usually the next question.
   */
  async function record() {
    if (!data) return;
    setError(null);
    setNotice(null);
    if (withQuestions.length === 0) {
      setNotice({
        text: "None of this class’s strands has questions yet, so there are no levels to record.",
      });
      return;
    }
    setBusy("record");
    try {
      const results = await Promise.all(
        withQuestions.map((s) => api.post<Assessment>(`/api/strands/${s.strand_id}/assess`)),
      );
      const recorded = results.reduce((n, r) => n + r.estimates_recorded, 0);
      const skipped = results.reduce((n, r) => n + r.skipped_insufficient_evidence, 0);
      const flags = results.reduce((n, r) => n + r.new_flags, 0);
      const parts = [`Saved levels for ${plural(recorded, "learner", "learners")}.`];
      if (skipped > 0) {
        parts.push(
          `${plural(skipped, "learner hasn’t", "learners haven’t")} answered enough ` +
            "questions yet, so no level was saved for them.",
        );
      }
      parts.push(
        flags > 0
          ? `${plural(flags, "learner now needs", "learners now need")} support.`
          : "Nobody new needs support — a learner is added after two low results in a row.",
      );
      setNotice({ text: parts.join(" "), link: flags > 0 });
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Could not record levels"));
    } finally {
      setBusy(null);
    }
  }

  const title = data ? `${data.grade}${data.name ? ` ${data.name}` : ""}` : "Class";
  const counts = data
    ? `${plural(data.learners.length, "learner", "learners")} · ` +
      plural(data.strands.length, "strand", "strands")
    : undefined;

  return (
    <>
      <PageHeader
        back={{ href: "/classrooms", label: "Classes" }}
        eyebrow="Class"
        title={title}
        description={counts}
        actions={
          <ButtonLink href={`/classrooms/${classId}/roll`} variant="secondary">
            <Icon name="users" />
            Manage learners
          </ButtonLink>
        }
      />

      <div className="space-y-3">
        <Note tone="error">{error}</Note>
        {notice && (
          <Note tone="ok">
            {notice.text}{" "}
            {notice.link && (
              <Link href={HOME} className="font-semibold underline underline-offset-2">
                See who
              </Link>
            )}
          </Note>
        )}
      </div>

      {!data && !error && <Loading what="the class" />}

      {data && data.learners.length === 0 && (
        <Empty
          title="No learners in this class yet"
          action={
            <ButtonLink href={`/classrooms/${classId}/roll`} variant="primary">
              Add learners
            </ButtonLink>
          }
        >
          Add your learners first, then give the class a quiz to see where each
          one is.
        </Empty>
      )}

      {data && data.learners.length === 0 && (
        <div className="mt-6">
          <ClassStrands
            classId={classId}
            classGrade={data.grade}
            strands={data.strands}
            onChange={reload}
          />
        </div>
      )}

      {data && data.learners.length > 0 && (
        <div className="space-y-6">
          <section aria-labelledby="actions-heading">
            <h2 id="actions-heading" className="sr-only">Actions</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <ActionTile
                href={`/classrooms/${classId}/administer`}
                icon="phone"
                title="Quiz on a device"
                body="Learners answer one at a time"
                primary
              />
              <ActionTile
                href={`/classrooms/${classId}/quiz`}
                icon="paper"
                title="Mark a paper quiz"
                body="Print, then mark each learner"
              />
              <ActionTile
                icon="save"
                title={busy === "record" ? "Saving…" : "Record levels"}
                body="After a quiz. Two low results add a learner to Support"
                onClick={record}
                disabled={busy !== null}
              />
              <ActionTile
                icon="refresh"
                title={busy === "calibrate" ? "Working…" : "Recalibrate"}
                body="Re-check how hard each question is"
                onClick={calibrate}
                disabled={busy !== null}
              />
            </div>
          </section>

          <ClassStrands
            classId={classId}
            classGrade={data.grade}
            strands={data.strands}
            onChange={reload}
          />

          {evidence && evidence.strands.length > 0 && (
            <Card className="p-4">
              <div className="mb-5 flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-brand-fill text-brand-strong">
                  <Icon name="trend" />
                </span>
                <h2 className="text-lg font-semibold text-ink">How the class is doing</h2>
              </div>
              <ClassSummary data={evidence} />
            </Card>
          )}

          {evidence && evidence.strands.length > 0 && (
            <section aria-labelledby="learners-heading">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h2 id="learners-heading" className="text-lg font-semibold text-ink">
                  Learners
                </h2>
                <Segmented
                  label="Sort learners"
                  value={order}
                  onChange={setOrder}
                  options={[
                    { value: "need", label: "Most need first" },
                    { value: "name", label: "A–Z" },
                  ]}
                />
              </div>
              <div className="mb-3">
                <Legend minimum={data.minimum_responses} />
              </div>
              <Card className="p-2 sm:p-3">
                <Heatmap data={evidence} order={order} />
              </Card>
              <p className="mt-4 text-sm text-ink-subtle">
                Levels are estimated from the answers recorded so far. A level
                marked provisional is based on fewer than {data.confident_responses}{" "}
                answers — useful, but check it before acting on it alone.
              </p>
            </section>
          )}
        </div>
      )}
    </>
  );
}

/** One of the class's four jobs: an icon, a name and one line on what it does. */
function ActionTile({
  icon,
  title,
  body,
  href,
  onClick,
  disabled,
  primary = false,
}: {
  icon: IconName;
  title: string;
  body: string;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  const className = `group flex h-full min-h-32 flex-col items-start gap-3 rounded-2xl border p-4 text-left
    shadow-soft transition-all hover:-translate-y-0.5 hover:shadow-lift disabled:cursor-not-allowed
    disabled:opacity-60 disabled:hover:translate-y-0 ${
      primary ? "border-transparent bg-action text-action-ink" : "border-line bg-surface text-ink"
    }`;
  const inner = (
    <>
      <span
        className={`flex size-10 items-center justify-center rounded-xl ${
          primary ? "bg-white/15" : "bg-brand-fill text-brand-strong"
        }`}
      >
        <Icon name={icon} />
      </span>
      <span>
        <span className="block text-[15px] font-semibold">{title}</span>
        <span className={`mt-0.5 block text-sm leading-snug ${primary ? "opacity-85" : "text-ink-muted"}`}>
          {body}
        </span>
      </span>
    </>
  );
  return href ? (
    <Link href={href} className={className}>
      {inner}
    </Link>
  ) : (
    <button type="button" onClick={onClick} disabled={disabled} className={className}>
      {inner}
    </button>
  );
}
