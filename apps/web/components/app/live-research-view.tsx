"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Circle,
  CircleCheck,
  Clock3,
  Globe2,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  terminalRunStatuses,
  useRunEvents,
  type RunProgressEvent,
  type RunStatus,
} from "@/hooks/use-run-events";

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

const researchStages: Array<{ status: Exclude<RunStatus, "COMPLETED" | "FAILED" | "CANCELLED">; detail: string }> = [
  { status: "QUEUED", detail: "Run accepted and added to the research queue." },
  { status: "VALIDATING", detail: "Checking the submitted claim and research constraints." },
  { status: "DECOMPOSING", detail: "Breaking the submission into verifiable claims." },
  { status: "RESEARCHING", detail: "Searching the web and authoritative source collections." },
  { status: "EXTRACTING", detail: "Extracting and normalizing relevant evidence." },
  { status: "ANALYZING_PROVENANCE", detail: "Assessing source provenance and independence." },
  { status: "SCORING", detail: "Scoring evidence relevance, support, and quality." },
  { status: "SYNTHESIZING", detail: "Drafting findings and their evidence-based reasoning." },
  { status: "AUDITING", detail: "Verifying citations and final report checks." },
];

const stagePosition = Object.fromEntries(
  researchStages.map((stage, index) => [stage.status, index + 1]),
) as Record<(typeof researchStages)[number]["status"], number>;

function timeLabel(value: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function firstEventByStage(events: RunProgressEvent[]) {
  const firstByStage = new Map<RunStatus, RunProgressEvent>();
  for (const event of events) {
    if (!firstByStage.has(event.stage)) firstByStage.set(event.stage, event);
  }
  return firstByStage;
}

export function LiveResearchView({ runId }: { runId: string }) {
  const router = useRouter();
  const {
    runQuery,
    latestEvent,
    progressHistoryQuery,
    cancelMutation,
    retryMutation,
    refreshDurableResult,
  } =
    useRunEvents(runId);
  const durableStatus = runQuery.data?.status;
  const durableTerminal = terminalRunStatuses.includes(
    durableStatus as (typeof terminalRunStatuses)[number],
  );
  const status: RunStatus =
    durableTerminal && durableStatus
      ? durableStatus
      : latestEvent?.stage ?? durableStatus ?? "QUEUED";
  const terminal = terminalRunStatuses.includes(status as (typeof terminalRunStatuses)[number]);
  const events = progressHistoryQuery.data ?? (latestEvent ? [latestEvent] : []);
  const firstEvents = firstEventByStage(events);
  const latestHistoryEvent = events.at(-1);
  const lastReachedStage = Math.max(
    1,
    ...events.map((event) => stagePosition[event.stage as keyof typeof stagePosition] ?? 0),
  );
  const completedSteps = status === "COMPLETED" ? researchStages.length :
    stagePosition[status as keyof typeof stagePosition] ?? lastReachedStage;
  const totalSteps = researchStages.length;
  const inaccessibleCount = latestEvent?.inaccessible_count ?? 0;
  const latestMessage =
    durableTerminal && latestEvent?.stage !== durableStatus
      ? runQuery.data?.failure_message ?? `Verification ${status.toLowerCase()}.`
      : latestEvent?.message ?? latestHistoryEvent?.message ?? "Waiting for the next public research update.";

  const progressHeading = status === "COMPLETED"
    ? "Research complete"
    : status === "FAILED"
      ? "Research stopped"
      : status === "CANCELLED"
        ? "Research cancelled"
        : stageLabels[status];

  if (runQuery.isLoading) {
    return <div className="flex min-h-64 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }
  if (runQuery.error) {
    return <Card><CardContent className="grid gap-3 p-6 text-sm text-destructive" role="alert"><span>{runQuery.error.message}</span><Button className="w-fit" variant="secondary" onClick={() => void runQuery.refetch()}><RefreshCw className="h-4 w-4" aria-hidden="true"/>Retry loading</Button></CardContent></Card>;
  }

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-5">
      <header>
        <h1 className="font-editorial text-4xl font-normal tracking-[-0.025em] text-foreground sm:text-5xl">Live research</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Follow the public stages of this evidence review as Elara gathers, evaluates, and cites timestamped sources.</p>
      </header>

      <Card className="overflow-hidden">
        <div role="status" aria-live="polite" className="border-b bg-card px-5 py-5 sm:px-7">
          <div className="flex items-start gap-4">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-subtle">
              {status === "COMPLETED" ? <CheckCircle2 className="h-6 w-6" aria-hidden="true" /> : terminal ? <XCircle className="h-6 w-6" aria-hidden="true" /> : <Globe2 className="h-6 w-6" aria-hidden="true" />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-editorial text-2xl font-normal tracking-[-0.015em]">{progressHeading}</p>
              <p className="mt-1 text-sm text-muted-foreground">{latestMessage}</p>
            </div>
            <span className="hidden items-center gap-2 whitespace-nowrap pt-1 text-sm text-primary sm:flex">
              {terminal ? <Check className="h-4 w-4" aria-hidden="true" /> : <Clock3 className="h-4 w-4" aria-hidden="true" />}
              {terminal ? "Finished" : "In progress"}
            </span>
          </div>
        </div>

        <CardContent className="grid gap-5 p-5 sm:p-7">
          <div>
            <div className="mb-2 flex items-baseline justify-between gap-4 text-sm">
              <span className="font-medium">{completedSteps} of {totalSteps} stages</span>
              <span className="tabular-nums text-muted-foreground">{Math.round((completedSteps / totalSteps) * 100)}%</span>
            </div>
            <div role="progressbar" aria-label="Verification progress" aria-valuemin={0} aria-valuemax={totalSteps} aria-valuenow={completedSteps} aria-valuetext={`${completedSteps} of ${totalSteps} research stages reached`} className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${(completedSteps / totalSteps) * 100}%` }} />
            </div>
          </div>

          <ol aria-label="Verification research stages" className="overflow-hidden rounded-lg border divide-y">
            {researchStages.map((stage, index) => {
              const event = firstEvents.get(stage.status);
              const isCurrent = !terminal && status === stage.status;
              // The durable public stage order is authoritative even if an older
              // Redis event has expired before its timestamp can be loaded.
              const isComplete = status === "COMPLETED" || index + 1 < completedSteps;
              const state = isComplete ? "complete" : isCurrent ? "current" : "pending";
              return (
                <li key={stage.status} className="grid min-h-16 grid-cols-[2.25rem_2rem_minmax(0,1fr)_4.5rem] items-center gap-2 px-3 py-3 sm:grid-cols-[2.75rem_2.5rem_minmax(9rem,1fr)_minmax(12rem,1.35fr)_5.5rem] sm:px-4">
                  <span className="relative flex h-full items-center justify-center" aria-hidden="true">
                    {index > 0 && <span className="absolute -top-3 h-3 w-px bg-border" />}
                    {index < researchStages.length - 1 && <span className="absolute -bottom-3 h-3 w-px bg-border" />}
                    {state === "complete" ? <CircleCheck className="h-6 w-6 fill-emerald-700 text-white" /> : state === "current" ? <span className="grid h-6 w-6 place-items-center rounded-full border-2 border-primary bg-card"><Loader2 className="h-3.5 w-3.5 animate-spin text-primary motion-reduce:animate-none" /></span> : <Circle className="h-6 w-6 text-muted-foreground/70" />}
                  </span>
                  <span className="font-editorial text-lg tabular-nums text-foreground">{index + 1}</span>
                  <div className="min-w-0">
                    <p className={state === "current" ? "font-medium text-primary" : "font-medium"}>{stageLabels[stage.status]}</p>
                    <p className="mt-0.5 text-xs leading-5 text-muted-foreground sm:hidden">{stage.detail}</p>
                    <span className="sr-only">{state === "complete" ? "Completed" : state === "current" ? "In progress" : "Pending"}</span>
                  </div>
                  <p className="hidden text-sm leading-5 text-muted-foreground sm:block">{stage.detail}</p>
                  <time dateTime={event?.created_at} className="text-right font-mono text-xs tabular-nums text-muted-foreground">{timeLabel(event?.created_at)}</time>
                </li>
              );
            })}
          </ol>

          {runQuery.data?.failure_message && <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><XCircle className="h-4 w-4 shrink-0" /> {runQuery.data.failure_message}</div>}
          {inaccessibleCount > 0 && <div className="flex gap-2 rounded-md border bg-muted/50 p-3 text-sm text-muted-foreground"><AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" /><p><strong className="text-foreground">{inaccessibleCount} source{inaccessibleCount === 1 ? " was" : "s were"} inaccessible.</strong> This limitation will be retained in the report.</p></div>}

          <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
            <Button variant="secondary" onClick={() => void refreshDurableResult()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh</Button>
            {!terminal && <Button variant="destructive" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending || Boolean(runQuery.data?.cancellation_requested_at)}>{runQuery.data?.cancellation_requested_at ? "Cancellation requested" : "Cancel research"}</Button>}
            {status === "COMPLETED" && <Button asChild><Link href={`/report/${runId}`}>Open report</Link></Button>}
            {(status === "FAILED" || status === "CANCELLED") && <Button disabled={retryMutation.isPending} onClick={async () => { const result = await retryMutation.mutateAsync(); router.push(`/verify/${result.run_id}`); }}>{retryMutation.isPending ? "Retrying" : "Retry verification"}</Button>}
          </div>
          {cancelMutation.error && <p className="text-xs text-destructive" role="alert">{cancelMutation.error.message}</p>}
          {retryMutation.error && <p className="text-xs text-destructive" role="alert">{retryMutation.error.message}</p>}
        </CardContent>
      </Card>
    </div>
  );
}
