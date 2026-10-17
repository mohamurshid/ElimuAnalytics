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
 */

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Legend } from "@/components/Heatmap";
import { Button, Empty, Loading, Note } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { shortTier, tierColour } from "@/lib/tiers";
import type { LearnerDiagnostics, Report } from "@/lib/types";

const MINIMUM = 5;

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
    ? new Date(report.generated_at).toLocaleString()
    : "";

  return (
    <div className="mt-3 rounded border border-neutral-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-2 py-0.5 text-xs font-semibold
                      ${verdictStyle(report.verdict)}`}
        >
          {report.verdict ?? "no verdict"}
        </span>
        <span className="text-xs text-neutral-500">{generated}</span>
      </div>

      {/* The server's own sentence. Paraphrasing it is how a refusal turns
          into an apparent fault. */}
      <p className="mt-2 text-sm text-neutral-700">{report.detail}</p>

      {report.exportable ? (
        <p className="mt-1 text-sm text-green-800">
          Every citation was verified against the retrieved KICD curriculum.
          This report is fit to send home.
        </p>
      ) : (
        <p className="mt-1 text-sm text-red-800">
          This report cannot be sent home.
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

      <p className="mt-4 text-xs text-neutral-500">
        {report.model}
        {report.effort ? ` · effort ${report.effort}` : ""}
        {report.cost_usd !== null
          ? ` · ${(report.cost_usd * 100).toFixed(3)} cents`
          : ""}
        {report.top_similarity !== null
          ? ` · curriculum match ${report.top_similarity.toFixed(3)}`
          : ""}
      </p>
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
    // Guarded here as well as by the disabled attribute: a keyboard repeat or
    // a second tab would otherwise spend twice.
    if (generating) return;
    setGenerating(strandId);
    setReportError(null);
    try {
      const created = await api.post<Report>(
        `/api/students/${id}/reports?strand_id=${strandId}`,
      );
      setReports((prev) => [created, ...(prev ?? [])]);
      setOpen(created.report_id);
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
              const busy = generating === cell.strand_id;
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
                        disabled={generating !== null}
                        onClick={() => generate(cell.strand_id)}
                      >
                        {busy
                          ? "Generating…"
                          : report
                            ? "Generate again"
                            : "Generate report"}
                      </Button>

                      {report && !busy && (
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
                                        ${verdictStyle(report.verdict)}`}
                          >
                            {report.verdict}
                          </span>
                        </>
                      )}

                      {busy && (
                        <span className="text-sm text-neutral-600">
                          English and Kiswahili, ten to thirty seconds.
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
