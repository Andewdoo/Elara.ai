import Link from "next/link";
import { CheckCircle2, Clock3, Loader2, Search, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const liveSteps = [
  { label: "Run persisted", detail: "FastAPI returned a durable run id", icon: CheckCircle2, done: true },
  { label: "Input decomposed", detail: "Atomic claims created for the report mock", icon: CheckCircle2, done: true },
  { label: "Sources selected", detail: "Primary, secondary, and inaccessible sources tracked", icon: Search, done: true },
  { label: "Citation audit", detail: "Terminal status invalidates report query", icon: Loader2, done: false },
];

export default async function VerifyRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <Card>
        <CardHeader>
          <CardTitle>Live research view</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {liveSteps.map((step) => {
            const Icon = step.icon;
            return (
              <div key={step.label} className="flex gap-3 rounded-md border bg-white p-4">
                <Icon className={step.done ? "h-5 w-5 text-emerald-700" : "h-5 w-5 animate-spin text-primary"} aria-hidden="true" />
                <div>
                  <p className="font-semibold">{step.label}</p>
                  <p className="text-sm text-muted-foreground">{step.detail}</p>
                </div>
              </div>
            );
          })}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted p-3">
            <span className="text-sm text-muted-foreground">Mocked SSE progress for {runId}</span>
            <Button asChild>
              <Link href={`/report/${runId}`}>Open completed report</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card className="self-start">
        <CardHeader>
          <CardTitle>Observable events</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm">
          <span className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-primary" /> 4 of 5 stages complete</span>
          <span className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-amber-700" /> 1 inaccessible source recorded</span>
          <p className="text-muted-foreground">Future SSE events will show public progress only, never private reasoning transcripts.</p>
        </CardContent>
      </Card>
    </div>
  );
}
