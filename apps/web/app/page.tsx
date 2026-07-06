import Link from "next/link";
import { ArrowRight, Database, GitBranch, ShieldCheck } from "lucide-react";

import { HistoryList } from "@/components/app/history-list";
import { StatusStrip } from "@/components/app/status-strip";
import { VerifyForm } from "@/components/app/verify-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function HomePage() {
  return (
    <div className="grid gap-5">
      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="grid gap-4">
          <div className="rounded-lg border bg-white p-5 shadow-subtle">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="info">Evidence workspace</Badge>
              <Badge tone="support">API-backed reports</Badge>
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-normal">Verification workspace</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
              Submit a claim, quote, article URL, pasted article, or document note. Completed reports reload durable runs, evidence, sources, graphs, and calculations from FastAPI.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button asChild>
                <Link href="/verify" className="inline-flex items-center gap-2">
                  Open verifier
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </div>
          <VerifyForm />
        </div>
        <div className="grid gap-4">
          <Card>
            <CardHeader>
            <CardTitle>Report guarantees</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="rounded-md border bg-muted/40 p-3"><span className="text-xs text-muted-foreground">Report source</span><p className="mt-1 text-lg font-semibold">PostgreSQL via FastAPI</p></div>
              <div className="grid grid-cols-2 gap-2">
                <Signal icon={ShieldCheck} label="Claims" value="Atomic" />
                <Signal icon={GitBranch} label="Sources" value="Traceable" />
                <Signal icon={Database} label="Scores" value="Server records" />
                <Signal icon={ShieldCheck} label="Evidence" value="Citation audited" />
              </div>
              <p className="text-xs leading-5 text-muted-foreground">Every completed report states when its evidence was reviewed.</p>
            </CardContent>
          </Card>
          <StatusStrip />
        </div>
      </section>
      <HistoryList />
    </div>
  );
}

function Signal({ icon: Icon, label, value }: { icon: typeof ShieldCheck; label: string; value: string }) {
  return (
    <div className="rounded-md border bg-white p-3">
      <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
      <span className="mt-2 block text-xs text-muted-foreground">{label}</span>
      <span className="block text-sm font-semibold">{value}</span>
    </div>
  );
}
