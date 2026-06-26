"use client";

import { Loader2 } from "lucide-react";

import { ReportWorkspace } from "@/components/report/report-workspace";
import { useMockedReport } from "@/hooks/use-mocked-report";

export function ReportRoute({ runId }: { runId: string }) {
  const reportQuery = useMockedReport(runId);

  if (reportQuery.isLoading) {
    return (
      <div className="flex min-h-96 items-center justify-center rounded-lg border bg-white">
        <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden="true" />
        <span className="ml-2 text-sm text-muted-foreground">Loading report record</span>
      </div>
    );
  }

  return <ReportWorkspace runId={runId} report={reportQuery.data} />;
}
