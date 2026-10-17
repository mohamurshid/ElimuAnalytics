"use client";

/**
 * One learner, every strand, and the reports generated for them.
 *
 * The page a teacher opens before acting on a flag, so it has to carry the
 * reasoning and not just the verdict: how many items the estimate rests on,
 * whether it is firm enough to act on, and — when there is no estimate — the
 * server's own sentence explaining why not.
 *
 * Three decisions about the report action are worth knowing before reading the
 * code.
 *
 * **A strand with no ability estimate gets no button.** The engine declines to
 * estimate below five answered items and the endpoint refuses to report on
 * what it cannot measure, so offering the action would be offering a 409. The
 * cell's own message already says why.
 *
 * **One generation at a time, and the button disables while it runs.**
 * Generation is two sequential model calls with adaptive thinking and takes
 * ten to thirty seconds. A teacher who clicks twice would create two reports
 * and spend twice the money. This is deliberately a UI guard rather than
 * server-side idempotency: regenerating a report IS legitimate — a teacher may
 * want a second attempt after a failed grounding check — so the server must
 * not refuse a repeat. What must not happen is an accidental repeat, and
 * disabling the control is the proportionate fix.
 *
 * **Existing reports are loaded on mount.** Without that, a generated report
 * would vanish on reload and the feature would look broken, which is the same
 * class of mistake as an empty heatmap cell reading as a rendering fault.
 *
 * **The two mount requests settle independently.** They were a `Promise.all`,
 * so either failure became one banner that named neither request - and when a
 * 500 did arrive it cost an hour to work out which of three calls had
 * produced it. Parallel is still right; collapsing their failures was not.
 *
 * **A pending report is polled, and the wait is counted out loud.** The
 * server answers 202 with an empty row and fills it about half a minute
 * later. The elapsed seconds are shown rather than a motionless
 * "Generating...", because an unchanging spinner is exactly what made a
 * working endpoint indistinguishable from a crashed one. Polling covers any
 * pending report in the list, not only one just asked for, so a reload in
 * the middle of a generation picks the wait back up instead of stranding it.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Legend } from "@/components/Heatmap";
import { Button, Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { shortTier, tierColour } from "@/lib/tiers";
import type { LearnerDiagnostics, Report } from "@/lib/types";

const MINIMUM = 5;

const POLL_MS = 2000;
// Two minutes against a generation that takes about 26 seconds. Past this
// something is wrong, and polling for ever would hide it behind a spinner.
const GIVE_UP_MS = 120_000;

/**
 * Parse a server timestamp as UTC.
 *
 * The API sends an aware ISO string, but a timestamp with no zone would be
 * read by `Date` as local time - which in Nairobi, three hours ahead, would
 * make every report look three hours old the moment it was created.
 */
function instant(iso: string): number {
  const zoned = /(Z|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(zoned ? iso : `${iso}Z`).getTime();
}

function secondsSince(iso: string | null): number | null {
  if (!iso) return null;
  const started = instant(iso);
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.round((Date.now() - started) / 1000));
}

/** What the badge says: the state first, the verdict only once there is one. */
function badgeLabel(report: Report): string {
  if (report.status === "pending") return "generating";
  if (report.status === "failed") return "failed";
  return report.verdict ?? "no verdict";
}

function badgeStyle(report: Report): string {
  if (report.status === "pending") {
    return "border-blue-300 bg-blue-50 text-blue-900";
  }
  if (report.status === "failed") {
    return "border-red-300 bg-red-50 text-red-900";
  }
  return verdictStyle(report.verdict);
}

/** GROUNDED is the only verdict that may be sent home. */
function verdictStyle(verdict: string | null): string {
  switch (verdict) {
    case "GROUNDED":
      return "border-green-300 bg-green-50 text-green-900";
    case "WEAK":
      return "border-amber-300 bg-amber-50 text-amber-900";
    case "FABRICATED":
      return "border-red-300 bg-red-50 text-red-900";
    default:
      return "border-neutral-300 bg-neutral-50 text-neutral-700";
  }
}

function ReportCard({ report }: { report: Report }) {
  const generated = report.generated_at
    ? new Date(instant(report.generated_at)).toLocaleString()
    : "";
  const pending = report.status === "pending";
  const elapsed = pending ? secondsSince(report.generated_at) : null;

  return (
    <div className="mt-3 rounded border border-neutral-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-2 py-0.5 text-xs font-semibold
                      ${badgeStyle(report)}`}
        >
          {badgeLabel(report)}
        </span>
        <span className="text-xs text-neutral-500">{generated}</span>
        {elapsed !== null && (
          <span className="text-xs text-neutral-600">{elapsed}s elapsed</span>
        )}
      </div>

      {/* The server's own sentence. Paraphrasing it is how a refusal turns
          into an apparent fault. */}
      <p className="mt-2 text-sm text-neutral-700">{report.detail}</p>

      {/* No second sentence about export. `detail` already carries the
          server's own account - "It can be exported", "cannot be exported or
          sent home" - and the paragraph that used to sit here said the same
          thing again in different words. Two sentences making one claim is
          how they drift apart. What is left is a marker, not prose, and only
          for a finished report: a pending row carries exportable=false
          because nothing has been checked yet, and a verdict on work not yet
          done is simply wrong. */}
      {report.status === "ready" && (
        <p
          className={`mt-1 text-sm ${
            report.exportable ? "text-green-800" : "text-red-800"
          }`}
        >
          {report.exportable ? "Fit to send home." : "Not fit to send home."}
        </p>
      )}

      {(["English", "Kiswahili"] as const).map((language) => {
        const body =
          language === "English" ? report.content_en : report.content_sw;
        const check = report.grounding?.[language];
        if (!body) return null;
        return (
          <section key={language} className="mt-4">
            <h3 className="text-sm font-semibold">{language}</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">
              {body}
            </p>
            {check && check.verbatim_quotes_verified.length > 0 && (
              <p className="mt-2 text-xs text-neutral-600">
                Verified citation
                {check.verbatim_quotes_verified.length > 1 ? "s" : ""}:{" "}
                {check.verbatim_quotes_verified
                  .map((quote) => `“${quote}”`)
                  .join("; ")}
              </p>
            )}
            {check && check.verbatim_quotes_fabricated.length > 0 && (
              <p className="mt-2 text-xs text-red-700">
                Not found in the curriculum:{" "}
                {check.verbatim_quotes_fabricated
                  .map((quote) => `“${quote}”`)
                  .join("; ")}
              </p>
            )}
          </section>
        );
      })}

      {report.status === "ready" && (
      <p className="mt-4 text-xs text-neutral-500">
        {report.model}
        {report.effort ? ` · effort ${report.effort}` : ""}
        {report.cost_usd !== null
          ? ` · ${(report.cost_usd * 100).toFixed(3)} cents`
          : ""}
        {report.top_similarity !== null
          ? ` · curriculum match ${report.top_similarity.toFixed(3)}`
          : ""}
        {report.duration_ms !== null
          ? ` · ${(report.duration_ms / 1000).toFixed(1)}s`
          : ""}
      </p>
      )}
    </div>
  );
}

export default function LearnerPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<LearnerDiagnostics | null>(null);
  const [reports, setReports] = useState<Report[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [stalled, setStalled] = useState(false);
  // Only to re-render the elapsed counter; the value is never read.
  const [, setTick] = useState(0);

  // Fired together, reported separately. Diagnostics failing means the page
  // has nothing to show; the report history failing means the page is intact
  // and one list is missing. Those are different sentences, and a teacher who
  // can still read the heatmap should not be told the learner failed to load.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const diagnostics = await api.get<LearnerDiagnostics>(
          `/api/students/${id}/diagnostics`,
        );
        if (cancelled) return;
        setData(diagnostics);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "No such learner at your school."
            : errorMessage(e, "Could not load this learner's diagnostics"),
        );
      }
    })();

    (async () => {
      try {
        const existing = await api.get<Report[]>(`/api/students/${id}/reports`);
        if (cancelled) return;
        setReports(existing);
        setHistoryError(null);
      } catch (e) {
        if (cancelled) return;
        setHistoryError(
          errorMessage(e, "Could not load this learner's earlier reports"),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [id]);

  /**
   * Every report still being generated, as a stable string.
   *
   * A string rather than an array so the polling effect restarts when the set
   * of pending reports actually changes, not every time `reports` is replaced
   * by an equal copy.
   */
  const watching = useMemo(
    () =>
      (reports ?? [])
        .filter((r) => r.status === "pending")
        .map((r) => r.report_id)
        .sort()
        .join(","),
    [reports],
  );

  const refresh = useCallback(async () => {
    setStalled(false);
    try {
      const existing = await api.get<Report[]>(`/api/students/${id}/reports`);
      setReports(existing);
      setHistoryError(null);
    } catch (e) {
      setHistoryError(errorMessage(e, "Could not refresh the reports"));
    }
  }, [id]);

  useEffect(() => {
    if (!watching) return;
    const ids = watching.split(",");
    const deadline = Date.now() + GIVE_UP_MS;
    let cancelled = false;

    const timer = setInterval(async () => {
      if (cancelled) return;
      if (Date.now() > deadline) {
        setStalled(true);
        clearInterval(timer);
        return;
      }
      try {
        const fresh = await Promise.all(
          ids.map((rid) =>
            api.get<Report>(`/api/students/${id}/reports/${rid}`),
          ),
        );
        if (cancelled) return;
        // Replaced in place, so the open card and the strand order are kept.
        setReports((prev) =>
          (prev ?? []).map(
            (r) => fresh.find((f) => f.report_id === r.report_id) ?? r,
          ),
        );
      } catch (e) {
        // One failed poll is not a failed report: the row is in the database
        // either way and the next tick will find it. A 404 is different - the
        // report or the learner is gone, and polling can only keep failing.
        if (e instanceof ApiError && e.status === 404) clearInterval(timer);
      }
    }, POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [watching, id]);

  // A second timer, only while something is pending, so the elapsed seconds
  // move once a second rather than in two-second jumps with the polling.
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [watching]);

  /** Strands with a generation already running. */
  const busyStrands = useMemo(
    () =>
      new Set(
        (reports ?? [])
          .filter((r) => r.status === "pending" && r.strand_id)
          .map((r) => r.strand_id as string),
      ),
    [reports],
  );

  /** The most recent report per strand, which is the one a teacher wants. */
  const latest = useMemo(() => {
    const map = new Map<string, Report>();
    for (const report of reports ?? []) {
      if (report.strand_id && !map.has(report.strand_id)) {
        map.set(report.strand_id, report);
      }
    }
    return map;
  }, [reports]);

  async function generate(strandId: string) {
    // Per strand now, not global: with generation off the request thread,
    // two strands can legitimately run at once. A repeat click on the SAME
    // strand is still refused here, and refused again by the server with a
    // 409 - which is the half that survives a second tab.
    if (generating === strandId || busyStrands.has(strandId)) return;
    setGenerating(strandId);
    setReportError(null);
    try {
      const created = await api.post<Report>(
        `/api/students/${id}/reports?strand_id=${strandId}`,
      );
      setReports((prev) => [created, ...(prev ?? [])]);
      setOpen(created.report_id);
      setStalled(false);
    } catch (e) {
      // A 500 carries FastAPI's generic body, which names neither the cause
      // nor the file. Every refusal this endpoint makes on purpose has its
      // own status and its own sentence, so a 500 that reaches here is an
      // unhandled exception - and the only copy of it is in the server log.
      setReportError(
        e instanceof ApiError && e.status === 500
          ? "The server failed while generating this report (HTTP 500). " +
            "The backend log has the traceback; this is a fault to fix, not " +
            "something to retry."
          : errorMessage(e, "Could not generate a report"),
      );
    } finally {
      setGenerating(null);
    }
  }

  return (
    <>
      <h1 className="text-2xl font-semibold">{data?.name ?? "Learner"}</h1>
      {data && !data.is_active && (
        <p className="mt-1 text-sm text-neutral-500">
          Withdrawn. Past responses are kept, and this learner is excluded from
          future calibration.
        </p>
      )}

      <div className="mt-4 space-y-2">
        <Note tone="error">{error}</Note>
        <Note tone="error">{historyError}</Note>
        <Note tone="error">{reportError}</Note>
      </div>

      {stalled && (
        <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-3
                        text-sm text-amber-900">
          This report is taking longer than two minutes. It may still be
          running - the work happens on the server, so nothing is lost either
          way.{" "}
          <button className="underline" onClick={refresh} type="button">
            Check again
          </button>
        </div>
      )}

      {!data && !error && (
        <div className="mt-6">
          <Loading what="diagnostics" />
        </div>
      )}

      {data && data.cells.length === 0 && (
        <div className="mt-6">
          <Empty>No strands have been assessed for this learner yet.</Empty>
        </div>
      )}

      {data && data.cells.length > 0 && (
        <>
          <div className="mt-6">
            <Legend minimum={MINIMUM} />
          </div>

          <ul className="mt-4 space-y-3">
            {data.cells.map((cell) => {
              const report = latest.get(cell.strand_id);
              const busy =
                generating === cell.strand_id ||
                busyStrands.has(cell.strand_id);
              const expanded = report && open === report.report_id;

              return (
                <li
                  key={cell.strand_id}
                  className="tier-cell rounded-r px-4 py-3"
                  style={{ ["--tier" as string]: tierColour(cell.tier) }}
                >
                  <div className="flex flex-wrap items-baseline justify-between
                                  gap-2">
                    <span className="font-medium">{cell.strand}</span>
                    <span className="text-sm">
                      {cell.theta === null ? (
                        <span className="text-neutral-600">no estimate</span>
                      ) : (
                        <>
                          <span className="font-medium">
                            {shortTier(cell.tier)}
                          </span>
                          <span className="text-neutral-600">
                            {" "}
                            · θ {cell.theta.toFixed(2)}
                          </span>
                        </>
                      )}
                    </span>
                  </div>
                  {/* The server's own words. Paraphrasing a refusal is how a
                      refusal turns into an apparent fault. */}
                  <p className="mt-1 text-sm text-neutral-600">
                    {cell.message}
                  </p>

                  {/* No estimate, no report. The endpoint would refuse, and
                      offering the action would be offering a 409. */}
                  {cell.theta !== null && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button
                        variant={report ? "secondary" : "primary"}
                        disabled={busy}
                        onClick={() => generate(cell.strand_id)}
                      >
                        {busy
                          ? "Generating…"
                          : report
                            ? "Generate again"
                            : "Generate report"}
                      </Button>

                      {report && (
                        <>
                          <Button
                            variant="secondary"
                            onClick={() =>
                              setOpen(expanded ? null : report.report_id)
                            }
                          >
                            {expanded ? "Hide report" : "Show report"}
                          </Button>
                          <span
                            className={`rounded border px-2 py-0.5 text-xs
                                        font-semibold
                                        ${badgeStyle(report)}`}
                          >
                            {badgeLabel(report)}
                          </span>
                        </>
                      )}

                      {busy && (
                        <span className="text-sm text-neutral-600">
                          English and Kiswahili, about half a minute. Leaving
                          this page will not stop it.
                        </span>
                      )}
                    </div>
                  )}

                  {expanded && report && <ReportCard report={report} />}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {reports !== null && reports.length === 0 && data && (
        <p className="mt-6 text-sm text-neutral-500">
          No reports generated yet. A report quotes the KICD curriculum
          verbatim and is checked against it before it can be sent home.
        </p>
      )}
    </>
  );
}
