"use client";

/**
 * A classroom's competency heatmap — the default view of a class.
 *
 * It leads rather than hiding behind the intervention queue because the
 * queue is a conclusion and this is the evidence for it. A teacher who only
 * ever sees the queue has to take the flagging on trust.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Heatmap, Legend } from "@/components/Heatmap";
import { Button, Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { Assessment, Heatmap as HeatmapData } from "@/lib/types";

export default function ClassHeatmapPage() {
  const { id: classId } = useParams<{ id: string }>();

  const [data, setData] = useState<HeatmapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchHeatmap = useCallback(
    () => api.get<HeatmapData>(`/api/classrooms/${classId}/heatmap`),
    [classId],
  );

  const failure = useCallback(
    (e: unknown) =>
      e instanceof ApiError && e.status === 404
        ? "No such classroom at your school."
        : errorMessage(e, "Could not load the heatmap"),
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

  /** Recalibrate every strand, then re-read. */
  async function calibrate() {
    if (!data) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const results = await Promise.all(
        data.strands.map((s) =>
          api.post<{ items_calibrated: number }>(
            `/api/strands/${s.strand_id}/calibrate`,
          ),
        ),
      );
      const items = results.reduce((n, r) => n + r.items_calibrated, 0);
      setNotice(
        `Calibrated ${items} items across ${results.length} strand(s). ` +
          "Item difficulty and discrimination are re-estimated from the " +
          "responses recorded so far.",
      );
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Calibration failed"));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Record an ability estimate for every learner, in every strand.
   *
   * Separate from calibration on purpose, and separate from viewing: an
   * assessment is an event in a learner's record, not a side effect of
   * opening a page. It is also the only way a flag can ever be raised, and a
   * flag needs two of these — so the notice says how many were recorded and
   * how many learners were skipped for want of evidence, which is usually the
   * question a teacher has next.
   */
  async function assess() {
    if (!data) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const results = await Promise.all(
        data.strands.map((s) =>
          api.post<Assessment>(`/api/strands/${s.strand_id}/assess`),
        ),
      );
      const recorded = results.reduce((n, r) => n + r.estimates_recorded, 0);
      const skipped = results.reduce(
        (n, r) => n + r.skipped_insufficient_evidence,
        0,
      );
      const flags = results.reduce((n, r) => n + r.new_flags, 0);
      setNotice(
        `Recorded ${recorded} estimate(s). ` +
          `${skipped} learner(s) were skipped for too little evidence — no ` +
          "number is stored for them, so they can never accumulate a flag. " +
          (flags > 0
            ? `${flags} new flag(s) raised; see the intervention queue.`
            : "No new flags: a flag needs two consecutive below-threshold " +
              "assessments, so run this again to see one."),
      );
      await reload();
    } catch (e) {
      setError(errorMessage(e, "Assessment failed"));
    } finally {
      setBusy(false);
    }
  }

  const title = data
    ? `${data.grade}${data.name ? ` ${data.name}` : ""}`
    : "Classroom";

  return (
    <>
      <Link
        href="/classrooms"
        className="text-sm text-neutral-500 hover:text-neutral-900"
      >
        ← All classrooms
      </Link>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <div className="flex items-center gap-3">
          <Link
            href={`/classrooms/${classId}/roll`}
            className="text-sm underline underline-offset-2
                       hover:text-neutral-500"
          >
            Roll
          </Link>
          <Button variant="secondary" disabled={busy || !data} onClick={calibrate}>
            Recalibrate
          </Button>
          <Button disabled={busy || !data} onClick={assess}>
            Run assessment
          </Button>
        </div>
      </div>

      <p className="mt-1 max-w-3xl text-sm text-neutral-600">
        Estimated competency per learner, per strand. A learner who has
        answered fewer than {data?.minimum_responses ?? 5} items in a strand
        gets no estimate at all — that is the system refusing to report a
        number derived from too little evidence, not missing data.
      </p>

      <div className="mt-4 space-y-3">
        <Note tone="error">{error}</Note>
        <Note>{notice}</Note>
      </div>

      {!data && !error && (
        <div className="mt-6">
          <Loading what="the heatmap" />
        </div>
      )}

      {data && data.learners.length === 0 && (
        <div className="mt-6">
          <Empty>
            No learners enrolled.{" "}
            <Link
              href={`/classrooms/${classId}/roll`}
              className="underline underline-offset-2"
            >
              Enrol some on the roll
            </Link>
            .
          </Empty>
        </div>
      )}

      {data && data.learners.length > 0 && (
        <>
          <div className="mt-6">
            <Legend minimum={data.minimum_responses} />
          </div>
          <div className="mt-3">
            <Heatmap data={data} />
          </div>
          <p className="mt-4 text-xs text-neutral-500">
            θ is the latent ability estimate for that strand. An estimate from
            fewer than {data.confident_responses} items is marked provisional:
            usable, but not yet firm enough to act on alone.
          </p>
        </>
      )}
    </>
  );
}
