import { BookOpenText, Calculator, FileSearch, GitBranch, ShieldCheck } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const principles = [
  { icon: ShieldCheck, title: "Narrow conclusion", text: "Reports evaluate the submitted claim, quotation, article, or document, not a permanent credibility score for a person or publisher." },
  { icon: FileSearch, title: "Evidence traceability", text: "Every factual conclusion is tied to exact passages, source snapshots, retrieval times, parser versions, and citation audit status." },
  { icon: GitBranch, title: "Source independence", text: "Derivative reporting is grouped so repeated stories do not count as independent corroboration." },
  { icon: Calculator, title: "Deterministic scoring", text: "Final arithmetic, thresholds, source multipliers, gates, and numerical audits belong in deterministic backend services." },
];

const scoreRoles = [
  ["Evidence support", "How strongly the stored evidence supports the factual claims."],
  ["Attribution support", "Whether the statement is accurately attributed to the named speaker or source."],
  ["Quote fidelity", "How faithfully a quotation or paraphrase matches its stored source passage."],
  ["Verdict confidence", "Confidence that the available evidence is sufficient for the report conclusion."],
  ["Source independence", "How much cited evidence comes from genuinely independent sources."],
  ["Context completeness", "Whether relevant surrounding context and limitations were captured."],
];

export default function MethodologyPage() {
  return (
    <div className="grid gap-5">
      <section className="rounded-lg border bg-white p-5">
        <div className="flex items-center gap-2 text-sm font-medium text-primary">
          <BookOpenText className="h-4 w-4" aria-hidden="true" />
          Evidence review methodology
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
      <section className="rounded-lg border bg-white p-5">
        <h2 className="text-lg font-semibold">Score roles</h2>
        <dl className="mt-3 grid gap-3 md:grid-cols-2">{scoreRoles.map(([term, description]) => <div key={term} className="rounded-md bg-muted p-3"><dt className="text-sm font-medium">{term}</dt><dd className="mt-1 text-sm leading-6 text-muted-foreground">{description}</dd></div>)}</dl>
      </section>
    </div>
  );
}
