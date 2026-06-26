import { BookOpenText, Calculator, FileSearch, GitBranch, ShieldCheck } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const principles = [
  { icon: ShieldCheck, title: "Narrow conclusion", text: "Reports evaluate the submitted claim, quotation, article, or document, not a permanent credibility score for a person or publisher." },
  { icon: FileSearch, title: "Evidence traceability", text: "Every factual conclusion is tied to exact passages, source snapshots, retrieval times, parser versions, and citation audit status." },
  { icon: GitBranch, title: "Source independence", text: "Derivative reporting is grouped so repeated stories do not count as independent corroboration." },
  { icon: Calculator, title: "Deterministic scoring", text: "Final arithmetic, thresholds, source multipliers, gates, and numerical audits belong in deterministic backend services." },
];

export default function MethodologyPage() {
  return (
    <div className="grid gap-5">
      <section className="rounded-lg border bg-white p-5">
        <div className="flex items-center gap-2 text-sm font-medium text-primary">
          <BookOpenText className="h-4 w-4" aria-hidden="true" />
          Methodology version 1.0 shell
        </div>
        <h1 className="mt-3 text-2xl font-semibold tracking-normal">Evidence-management methodology</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
          Elara.ai organizes available evidence as of a retrieval timestamp, separates attribution from factual content, records inaccessible sources, and exposes how report scores were produced.
        </p>
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        {principles.map((principle) => {
          const Icon = principle.icon;
          return (
            <Card key={principle.title}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                  {principle.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-muted-foreground">{principle.text}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
