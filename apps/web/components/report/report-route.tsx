"use client";

import Link from "next/link";
import { Loader2, RefreshCw } from "lucide-react";

import { ReportWorkspace } from "@/components/report/report-workspace";
import { useReportData } from "@/hooks/use-report-data";

export function ReportRoute({ runId }: { runId: string }) {
  const queries = useReportData(runId);
  const pending = queries.authLoading || queries.run.isLoading || (queries.run.data?.status === "COMPLETED" && queries.report.isLoading);
  const error = queries.run.error ?? queries.report.error;

  if (pending) {
    return (
      <div className="flex min-h-96 items-center justify-center rounded-lg border bg-white">
        <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
        <span className="ml-2 text-sm text-muted-foreground">Loading report record</span>
      </div>
    );
  }

  if (!queries.authenticated && !queries.run.data) {
    return <div role="alert" className="rounded-lg border bg-white p-4 text-sm text-muted-foreground">Sign in to view this report.</div>;
  }

  if (error || !queries.run.data) {
    return <div role="alert" className="grid gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"><span>{error instanceof Error ? error.message : "The report could not be loaded."}</span><ButtonRetry onClick={() => void Promise.all([queries.run.refetch(), queries.report.refetch()])} /></div>;
  }

  if (queries.run.data.status !== "COMPLETED") {
    const active = !["FAILED", "CANCELLED"].includes(queries.run.data.status);
    return <div className="grid gap-3 rounded-lg border bg-white p-5"><h1 className="text-lg font-semibold">Report not available</h1><p className="text-sm text-muted-foreground">{active ? "This verification is still running. Reopen live progress to continue." : `This verification ${queries.run.data.status.toLowerCase()} before a citation-audited report was completed.`}</p><div><Link className="inline-flex rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground" href={`/verify/${runId}`}>{active ? "Open live progress" : "Review and retry"}</Link></div></div>;
  }

  if (!queries.report.data) return null;

  const resourceFailures = [queries.sources.error ? "sources" : null, queries.sourceGraph.error ? "source graph" : null].filter((value): value is string => Boolean(value));

  return <><ReportWorkspace data={{ run: queries.run.data, report: queries.report.data, sources: queries.sources.data?.sources ?? [], sourceGraph: queries.sourceGraph.data ?? { nodes: [], edges: [] } }} />{resourceFailures.length > 0 && <div role="status" className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm"><span>Some report resources are unavailable: {resourceFailures.join(", ")}.</span><ButtonRetry onClick={() => void Promise.all([queries.sources.refetch(), queries.sourceGraph.refetch()])} /></div>}</>;
}

function ButtonRetry({ onClick }: { onClick: () => void }) { return <button type="button" className="inline-flex w-fit items-center gap-2 rounded-md border bg-white px-3 py-2 font-medium" onClick={onClick}><RefreshCw className="h-4 w-4" aria-hidden="true"/>Retry loading</button>; }
