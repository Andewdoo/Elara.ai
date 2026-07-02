"use client";

import { Loader2 } from "lucide-react";

import { ReportWorkspace } from "@/components/report/report-workspace";
import { useReportData } from "@/hooks/use-report-data";

export function ReportRoute({ runId }: { runId: string }) {
  const queries = useReportData(runId);
  const pending = queries.authLoading || [queries.run, queries.report, queries.sources, queries.sourceGraph].some((query) => query.isLoading);
  const error = [queries.run, queries.report, queries.sources, queries.sourceGraph].find((query) => query.error)?.error;

  if (pending) {
    return (
      <div className="flex min-h-96 items-center justify-center rounded-lg border bg-white">
        <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
        <span className="ml-2 text-sm text-muted-foreground">Loading report record</span>
      </div>
    );
  }

  if (!queries.authenticated) {
    return <div role="alert" className="rounded-lg border bg-white p-4 text-sm text-muted-foreground">Sign in to view this report.</div>;
  }

  if (error || !queries.run.data || !queries.report.data || !queries.sources.data || !queries.sourceGraph.data) {
    return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">{error instanceof Error ? error.message : "The report could not be loaded."}</div>;
  }

  return <ReportWorkspace data={{ run: queries.run.data, report: queries.report.data, sources: queries.sources.data.sources, sourceGraph: queries.sourceGraph.data }} />;
}
