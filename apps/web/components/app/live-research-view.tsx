"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  Radio,
  Search,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { terminalRunStatuses, useRunEvents, type RunStatus } from "@/hooks/use-run-events";

const stageLabels: Record<RunStatus, string> = {
  QUEUED: "Queued",
  VALIDATING: "Validating input",
  DECOMPOSING: "Decomposing claims",
  RESEARCHING: "Researching sources",
  EXTRACTING: "Extracting evidence",
  ANALYZING_PROVENANCE: "Analyzing provenance",
  SCORING: "Scoring evidence",
  SYNTHESIZING: "Synthesizing report",
  AUDITING: "Auditing citations",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

function elapsedLabel(from: string | undefined, now: number) {
  if (!from) return "0:00";
  const seconds = Math.max(0, Math.floor((now - new Date(from).getTime()) / 1_000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function LiveResearchView({ runId }: { runId: string }) {
  const { runQuery, latestEvent, connectionState, pollingFallback, cancelMutation } =
    useRunEvents(runId);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);

  const durableStatus = runQuery.data?.status;
  const durableTerminal = terminalRunStatuses.includes(
    durableStatus as (typeof terminalRunStatuses)[number],
  );
  const status: RunStatus =
    durableTerminal && durableStatus
      ? durableStatus
      : latestEvent?.stage ?? durableStatus ?? "QUEUED";
  const terminal = terminalRunStatuses.includes(status as (typeof terminalRunStatuses)[number]);
  const sourceTotal = useMemo(
    () => Object.values(latestEvent?.source_counts ?? {}).reduce((sum, count) => sum + count, 0),
    [latestEvent?.source_counts],
  );
  const totalSteps = Math.max(1, latestEvent?.total_steps ?? 9);
  const completedSteps = Math.min(
    totalSteps,
    Math.max(0, status === "COMPLETED" ? totalSteps : latestEvent?.completed_steps ?? 0),
  );
  const inaccessibleCount = latestEvent?.inaccessible_count ?? 0;
  const terminalTime = terminal
    ? runQuery.data?.completed_at ?? runQuery.data?.failed_at ?? runQuery.data?.updated_at
    : undefined;
  const latestMessage =
    durableTerminal && latestEvent?.stage !== durableStatus
      ? runQuery.data?.failure_message ?? `Verification ${status.toLowerCase()}.`
      : latestEvent?.message ?? "Waiting for the next public research update.";

  if (runQuery.isLoading) {
    return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }
  if (runQuery.error) {
    return <Card><CardContent className="p-6 text-sm text-destructive" role="alert">{runQuery.error.message}</CardContent></Card>;
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>Live research view</CardTitle>
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <Radio className={connectionState === "connected" ? "h-3.5 w-3.5 text-emerald-600" : "h-3.5 w-3.5 text-amber-600"} />
              {pollingFallback ? "Polling PostgreSQL" : connectionState}
            </span>
          </div>
        </CardHeader>
        <CardContent className="grid gap-5">
          <div className="rounded-md border bg-white p-5">
            <div className="flex items-start gap-3">
              {status === "COMPLETED" ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-700" />
              ) : terminal ? (
                <XCircle className="mt-0.5 h-5 w-5 text-destructive" />
              ) : (
                <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-primary" />
              )}
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{stageLabels[status]}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {latestMessage}
                </p>
              </div>
            </div>
          </div>

          <div>
            <div className="mb-2 flex justify-between text-sm">
              <span>{completedSteps} of {totalSteps} steps</span>
              <span>{Math.round((completedSteps / totalSteps) * 100)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(completedSteps / totalSteps) * 100}%` }} />
            </div>
          </div>

          {runQuery.data?.failure_message && (
            <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              <XCircle className="h-4 w-4 shrink-0" /> {runQuery.data.failure_message}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            <span className="text-xs text-muted-foreground">Run {runId}</span>
            <div className="flex gap-2">
              {!terminal && (
                <Button
                  variant="destructive"
                  onClick={() => cancelMutation.mutate()}
                  disabled={cancelMutation.isPending || Boolean(runQuery.data?.cancellation_requested_at)}
                >
                  {runQuery.data?.cancellation_requested_at ? "Cancellation requested" : "Cancel research"}
                </Button>
              )}
              {status === "COMPLETED" && <Button asChild><Link href={`/report/${runId}`}>Open report</Link></Button>}
            </div>
          </div>
          {cancelMutation.error && <p className="text-xs text-destructive" role="alert">{cancelMutation.error.message}</p>}
        </CardContent>
      </Card>

      <div className="grid content-start gap-4">
        <Card>
          <CardHeader><CardTitle>Research telemetry</CardTitle></CardHeader>
          <CardContent className="grid gap-4 text-sm">
            <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-primary" /> Elapsed</span><strong>{elapsedLabel(runQuery.data?.started_at ?? runQuery.data?.queued_at, terminalTime ? new Date(terminalTime).getTime() : now)}</strong></span>
            <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><Search className="h-4 w-4 text-primary" /> Sources found</span><strong>{sourceTotal}</strong></span>
            {Object.entries(latestEvent?.source_counts ?? {}).map(([label, count]) => (
              <span key={label} className="flex items-center justify-between gap-2 pl-6 text-xs text-muted-foreground">
                <span>{label.replaceAll("_", " ").toLowerCase()}</span><strong>{count}</strong>
              </span>
            ))}
            <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-700" /> Inaccessible</span><strong>{inaccessibleCount}</strong></span>
          </CardContent>
        </Card>
        {inaccessibleCount > 0 && (
          <Card>
            <CardContent className="flex gap-3 p-4 text-sm">
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-700" />
              <p><strong>{inaccessibleCount} source{inaccessibleCount === 1 ? " was" : "s were"} inaccessible.</strong> The final report will preserve these evidence limitations.</p>
            </CardContent>
          </Card>
        )}
        <Card>
          <CardHeader><CardTitle>Latest public event</CardTitle></CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {latestMessage ?? "No stream event received yet. Private reasoning is never published here."}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
