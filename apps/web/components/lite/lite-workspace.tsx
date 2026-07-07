"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, FileSearch, GitBranch, Loader2, ShieldCheck } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/form-controls";
import type { LiteResponse } from "@/lib/lite/schemas";

const progressStages = [
  "Intake",
  "Evidence retrieval",
  "Citation audit",
  "Report",
] as const;

const samplePrompts = [
  "Did the transit budget add weekend rail service in 2025?",
  "What changed in the library hours update?",
  "Was the community health pilot approved?",
] as const;

type LiteInputHint = "claim" | "question" | "quote" | "paraphrase";

export function LiteWorkspace() {
  const [input, setInput] = useState("");
  const [inputTypeHint, setInputTypeHint] = useState<LiteInputHint>("question");
  const [result, setResult] = useState<LiteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const activeStage = useMemo(() => {
    if (isSubmitting) return "Evidence retrieval";
    if (!result) return "Intake";
    if (result.kind === "answer") return "Report";
    if (result.kind === "insufficient_evidence") return "Citation audit";
    return "Intake";
  }, [isSubmitting, result]);

  async function submitLiteRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) {
      setError("Enter a claim or question for the Lite evidence library.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/lite/answer", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          corpus_version: "lite-corpus-v1",
          input: trimmed,
          input_type_hint: inputTypeHint,
          client_trace_id: createClientTraceId(),
        }),
      });
      const body = (await response.json()) as LiteResponse;
      setResult(body);
      if (!response.ok || body.kind === "error") {
        setError(body.kind === "error" ? body.message : "Lite Mode could not complete this request.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Lite Mode could not reach the evidence library.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid gap-5">
      <section className="grid gap-4 lg:grid-cols-[1.18fr_0.82fr]">
        <div className="grid gap-4">
          <div className="rounded-lg border bg-white p-5 shadow-subtle">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="info">Lite evidence library</Badge>
              <Badge tone="support">Citation-audited demo</Badge>
            </div>
            <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <h1 className="text-3xl font-semibold tracking-normal">Evidence workspace</h1>
                <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
                  Ask a claim or question against Elara&apos;s curated stored evidence library. Lite reports show exact chunks, source labels, uncertainty, and citation-audit status.
                </p>
              </div>
              <Button asChild variant="secondary" className="md:mt-1">
                <Link href="/verify" className="inline-flex items-center gap-2">
                  Open Full Verifier
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>New Lite report</CardTitle>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4" onSubmit={submitLiteRequest}>
                <label className="grid gap-1 text-sm font-medium">
                  Request type
                  <Select value={inputTypeHint} onChange={(event) => setInputTypeHint(event.target.value as LiteInputHint)}>
                    <option value="question">Question</option>
                    <option value="claim">Claim</option>
                    <option value="quote">Quote</option>
                    <option value="paraphrase">Paraphrase</option>
                  </Select>
                </label>
                <label className="grid gap-1 text-sm font-medium" htmlFor="lite-target">
                  Claim or question
                  <Textarea
                    id="lite-target"
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    placeholder="Ask about a public demo topic in the curated evidence library."
                    aria-describedby="lite-scope"
                    maxLength={4000}
                  />
                  <span id="lite-scope" className="text-xs leading-5 text-muted-foreground">
                    Lite Mode answers only from selected stored evidence chunks and may return insufficient evidence.
                  </span>
                </label>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap gap-2" aria-label="Suggested Lite evidence-library prompts">
                    {samplePrompts.map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        className="rounded-md border bg-white px-2.5 py-1.5 text-left text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground"
                        onClick={() => setInput(prompt)}
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                  <Button type="submit" disabled={isSubmitting}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FileSearch className="h-4 w-4" aria-hidden="true" />}
                    Run Lite report
                  </Button>
                </div>
                {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
              </form>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Report progress</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              {progressStages.map((stage) => {
                const isActive = stage === activeStage;
                const isComplete = result?.kind === "answer" || (result?.kind === "insufficient_evidence" && stage !== "Report");
                return (
                  <div key={stage} className="flex items-center gap-3 rounded-md border bg-white px-3 py-2">
                    <span className="flex h-7 w-7 items-center justify-center rounded-md bg-muted text-primary">
                      {isSubmitting && isActive ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="h-4 w-4" aria-hidden="true" />}
                    </span>
                    <span className="text-sm font-medium">{stage}</span>
                    <Badge tone={isActive ? "info" : isComplete ? "support" : "neutral"}>{isActive ? "Active" : isComplete ? "Ready" : "Queued"}</Badge>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Report scope</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <Signal icon={FileSearch} label="Evidence" value="Curated stored chunks" />
              <Signal icon={GitBranch} label="Sources" value="Exact chunk labels" />
              <Signal icon={ShieldCheck} label="Audit" value="Citation presence checked" />
              <p className="text-xs leading-5 text-muted-foreground">
                Lite Mode is a public demo path for the stored evidence library, not the complete production verifier.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      <LiteResultPanel result={result} />
    </div>
  );
}

function LiteResultPanel({ result }: { result: LiteResponse | null }) {
  if (!result) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Report workspace</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm text-muted-foreground">
          <p>Submitted Lite runs appear here with cited sentences, selected evidence chunks, source labels, and audit status.</p>
        </CardContent>
      </Card>
    );
  }

  if (result.kind === "error") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Report workspace</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <p>{result.message}</p>
        </CardContent>
      </Card>
    );
  }

  const reviewed = new Date(result.reviewed_at).toLocaleString();

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>Report workspace</CardTitle>
          <Badge tone={result.kind === "answer" ? "support" : "warning"}>{result.audit_status}</Badge>
          <span className="text-xs text-muted-foreground">Run {result.run_id}</span>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <p className="text-sm text-muted-foreground">
          Evidence reviewed as of {reviewed}. New evidence or corrections may change this assessment.
        </p>
        {result.kind === "answer" ? (
          <>
            <div className="rounded-md border bg-muted/40 p-3">
              <span className="text-xs text-muted-foreground">Answer</span>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-6">{result.answer_markdown}</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <EvidenceList title="Cited sentences" items={result.cited_sentences.map((sentence) => `${sentence.text} [${sentence.source_labels.join(", ")}]`)} />
              <EvidenceList title="Selected evidence" items={result.selected_context.chunks.map((chunk) => `${chunk.source_label}: ${chunk.heading_path ?? chunk.page_or_position ?? chunk.source_title}`)} />
            </div>
          </>
        ) : (
          <div className="rounded-md border bg-muted/40 p-3">
            <span className="text-xs text-muted-foreground">Insufficient evidence</span>
            <p className="mt-1 text-sm leading-6">{result.message}</p>
            {result.gaps.length > 0 && <EvidenceList title="Gaps" items={result.gaps} />}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border bg-white p-3">
      <p className="text-sm font-semibold">{title}</p>
      <ul className="mt-2 grid gap-2 text-sm text-muted-foreground">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Signal({ icon: Icon, label, value }: { icon: typeof FileSearch; label: string; value: string }) {
  return (
    <div className="rounded-md border bg-white p-3">
      <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
      <span className="mt-2 block text-xs text-muted-foreground">{label}</span>
      <span className="block text-sm font-semibold">{value}</span>
    </div>
  );
}

function createClientTraceId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `lite-${Date.now()}`;
}
