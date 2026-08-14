"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Clock3, FileCheck2, FolderOpen, ShieldCheck } from "lucide-react";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiErrorMessage, authenticatedApiFetch } from "@/lib/auth";
import { DEMO_RUN_LIMIT, type DemoRun } from "@/lib/demo/demo-runs";

type DemoRunsResponse = {
  items: DemoRun[];
  total: number;
};

const completedDateFormat = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeZone: "UTC",
});

export function DemoWorkspace() {
  const { user, loading: authLoading } = useFirebaseAuth();
  const runsQuery = useQuery({
    queryKey: ["demo-runs"],
    enabled: Boolean(user),
    queryFn: async () => {
      if (!user) throw new Error("Sign in to load Demo runs.");
      const response = await authenticatedApiFetch(user, "/v1/demo-runs");
      if (!response.ok) throw new Error(await apiErrorMessage(response));
      return response.json() as Promise<DemoRunsResponse>;
    },
  });
  const demoRuns = runsQuery.data?.items ?? [];

  return (
    <div className="grid gap-10">
      <section className="max-w-3xl">
        <Badge tone="support" className="gap-1.5">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
          Read-only demo archive
        </Badge>
        <h1 className="mt-5 font-editorial text-4xl font-semibold leading-[1.04] tracking-[-0.035em] text-foreground sm:text-5xl">
          Completed verification runs.
        </h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-muted-foreground">
          This Demo displays 12 citation-audited full-version reports. It does not accept requests or retrieve new evidence.
        </p>
        <Button asChild variant="secondary" className="mt-6">
          <Link href="/verify">
            Open Full Verifier
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </Button>
      </section>

      <section aria-labelledby="demo-runs-heading" className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b pb-4">
          <div>
            <h2 id="demo-runs-heading" className="text-lg font-semibold text-foreground">Demo runs</h2>
            <p className="mt-1 text-sm text-muted-foreground">{demoRuns.length} of {Math.min(runsQuery.data?.total ?? DEMO_RUN_LIMIT, DEMO_RUN_LIMIT)} designated completed reports shown</p>
          </div>
          <span className="font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">Designated reports only</span>
        </div>

        {authLoading || runsQuery.isLoading ? <LoadingDemoRuns /> : !user ? <SignedOutDemoRuns /> : runsQuery.error ? <DemoRunsError onRetry={() => void runsQuery.refetch()} /> : demoRuns.length ? <div className="grid gap-3">{demoRuns.map((run) => <DemoRunCard key={run.run_id} run={run} />)}</div> : <EmptyDemoRuns />}
      </section>
    </div>
  );
}

function DemoRunCard({ run }: { run: DemoRun }) {
  const title = run.title?.trim() || run.submitted_text_preview || "Verification report";
  const reviewedAt = run.evidence_reviewed_at ?? run.updated_at;

  return (
    <Card className="transition-colors duration-200 hover:border-primary/40 motion-reduce:transition-none">
      <CardContent className="grid gap-5 p-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="support">Completed</Badge>
            <span className="font-mono text-xs text-muted-foreground">Reviewed {completedDateFormat.format(new Date(reviewedAt))}</span>
          </div>
          <h3 className="mt-3 text-lg font-semibold tracking-[-0.015em] text-foreground">{title}</h3>
          {run.submitted_text_preview && run.submitted_text_preview !== title && <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{run.submitted_text_preview}</p>}
        </div>
        <div className="grid gap-3 sm:justify-items-end">
          <dl className="grid w-full grid-cols-3 divide-x rounded-md border bg-muted/30 text-center sm:w-[27rem]">
            <DemoMetric icon={ShieldCheck} label="Verdict" value={formatVerdict(run.verdict)} />
            <DemoMetric icon={FileCheck2} label="Depth" value={formatDepth(run.research_depth)} />
            <DemoMetric icon={Clock3} label="Audit" value="Complete" />
          </dl>
          <Button asChild size="sm" variant="secondary">
            <Link href={`/report/${run.run_id}`}>
              Open report
              <FolderOpen className="h-4 w-4" aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function DemoMetric({ icon: Icon, label, value }: { icon: typeof ShieldCheck; label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <Icon className="mx-auto h-4 w-4 text-primary" aria-hidden="true" />
      <dt className="mt-1.5 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-xs font-semibold text-foreground">{value}</dd>
    </div>
  );
}

function LoadingDemoRuns() {
  return <Card><CardContent className="flex min-h-40 items-center gap-3 p-6 text-sm text-muted-foreground"><Clock3 className="h-5 w-5 animate-pulse text-primary motion-reduce:animate-none" aria-hidden="true" />Loading shared Demo runs…</CardContent></Card>;
}

function SignedOutDemoRuns() {
  return <Card><CardContent className="grid min-h-40 place-items-center p-8 text-center"><div className="max-w-sm"><h3 className="text-base font-semibold text-foreground">Sign in to view Demo reports</h3><p className="mt-2 text-sm leading-6 text-muted-foreground">The designated full-version reports are identical for every account.</p></div></CardContent></Card>;
}

function DemoRunsError({ onRetry }: { onRetry: () => void }) {
  return <Card><CardContent className="flex flex-wrap items-center gap-3 p-6 text-sm text-destructive" role="alert"><span>Shared Demo runs could not be loaded.</span><Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button></CardContent></Card>;
}

function EmptyDemoRuns() {
  return <Card><CardContent className="grid min-h-56 place-items-center p-8 text-center"><div className="max-w-sm"><span className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-muted text-primary"><FileCheck2 className="h-5 w-5" aria-hidden="true" /></span><h3 className="mt-4 text-base font-semibold text-foreground">No Demo reports are available yet</h3><p className="mt-2 text-sm leading-6 text-muted-foreground">The shared Demo archive is being prepared.</p></div></CardContent></Card>;
}

function formatVerdict(value: string | null) {
  return value ? value.replaceAll("_", " ") : "Recorded";
}

function formatDepth(value: string) {
  return value.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}
