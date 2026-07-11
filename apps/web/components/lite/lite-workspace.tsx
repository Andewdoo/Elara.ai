"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, Circle, FileSearch, GitBranch, Loader2, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/form-controls";
import { ReportWorkspace } from "@/components/report/report-workspace";
import { isLiteReportResponse, liteResponseToReportWorkspace } from "@/lib/lite/report-adapter";
import type { LiteResponse } from "@/lib/lite/schemas";

const liteProgressStages = [
  {
    id: "intake",
    label: "Intake",
    description: "Validating the submitted claim or question.",
  },
  {
    id: "query_planning",
    label: "Query planning",
    description: "Planning bounded searches against the curated library.",
  },
  {
    id: "library_retrieval",
    label: "Library retrieval",
    description: "Selecting stored evidence chunks from the Lite corpus.",
  },
  {
    id: "evidence_review",
    label: "Evidence review",
    description: "Comparing selected chunks with the submitted request.",
  },
  {
    id: "synthesis",
    label: "Synthesis",
    description: "Drafting a cited answer from selected chunks only.",
  },
  {
    id: "citation_audit",
    label: "Citation audit",
    description: "Checking citation presence before showing the result.",
  },
] as const;

const samplePrompts = [
  "Did the transit budget add weekend rail service in 2025?",
  "What changed in the library hours update?",
  "Was the community health pilot approved?",
] as const;

type LiteInputHint = "claim" | "question" | "quote" | "paraphrase";
type LiteProgressStatus = "idle" | "loading" | "success" | "failure" | "cancelled";
type LiteStageStatus = "queued" | "active" | "complete" | "failed" | "cancelled";
type LiteSubmission = {
  input: string;
  inputTypeHint: LiteInputHint;
};

const finalOptimisticStageIndex = liteProgressStages.length - 1;

export function LiteWorkspace() {
  const [input, setInput] = useState("");
  const [inputTypeHint, setInputTypeHint] = useState<LiteInputHint>("question");
  const [result, setResult] = useState<LiteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progressStatus, setProgressStatus] = useState<LiteProgressStatus>("idle");
  const [activeStageIndex, setActiveStageIndex] = useState(0);
  const [lastSubmission, setLastSubmission] = useState<LiteSubmission | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);

  useEffect(() => {
    if (!isSubmitting) return;
    const timer = setInterval(() => {
      setActiveStageIndex((stageIndex) => Math.min(stageIndex + 1, finalOptimisticStageIndex));
    }, 850);
    return () => clearInterval(timer);
  }, [isSubmitting]);

  const progressSummary = useMemo(() => {
    if (progressStatus === "loading") return liteProgressStages[activeStageIndex].description;
    if (progressStatus === "success" && result?.kind === "answer") return "Citation-audited Lite report is ready.";
    if (progressStatus === "success" && result?.kind === "insufficient_evidence") return "Citation audit completed with an insufficient-evidence result.";
    if (progressStatus === "failure") return "Lite request stopped before a typed report was completed.";
    if (progressStatus === "cancelled") return "Lite request cancelled in this browser.";
    return "Submit a request to see request-local Lite progress.";
  }, [activeStageIndex, progressStatus, result?.kind]);

  async function submitLiteRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runLiteRequest({ input: input.trim(), inputTypeHint });
  }

  async function runLiteRequest(submission: LiteSubmission) {
    const trimmed = submission.input.trim();
    if (!trimmed) {
      setError("Enter a claim or question for the Lite evidence library.");
      return;
    }
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setLastSubmission({ input: trimmed, inputTypeHint: submission.inputTypeHint });
    setIsSubmitting(true);
    setProgressStatus("loading");
    setActiveStageIndex(0);
    setError(null);
    setResult(null);
    try {
      const response = await fetch("/api/lite/answer", {
        method: "POST",
        headers: { "content-type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          corpus_version: "lite-corpus-v1",
          input: trimmed,
          input_type_hint: submission.inputTypeHint,
          client_trace_id: createClientTraceId(),
        }),
      });
      const body = (await response.json()) as LiteResponse;
      if (requestSequenceRef.current !== requestId) return;
      setResult(body);
      if (!response.ok || body.kind === "error") {
        setProgressStatus("failure");
        setError(body.kind === "error" ? body.message : "Lite Mode could not complete this request.");
      } else {
        setProgressStatus("success");
        setActiveStageIndex(finalOptimisticStageIndex);
      }
    } catch (caught) {
      if (requestSequenceRef.current !== requestId) return;
      if (isAbortError(caught)) {
        setProgressStatus("cancelled");
        setError("Lite request cancelled. No background Lite worker is running.");
      } else {
        setProgressStatus("failure");
        setError(caught instanceof Error ? caught.message : "Lite Mode could not reach the evidence library.");
      }
    } finally {
      if (requestSequenceRef.current === requestId) {
        setIsSubmitting(false);
        abortControllerRef.current = null;
      }
    }
  }

  function cancelLiteRequest() {
    if (!isSubmitting) return;
    abortControllerRef.current?.abort();
  }

  function clearLiteWorkspace() {
    abortControllerRef.current?.abort();
    requestSequenceRef.current += 1;
    abortControllerRef.current = null;
    setInput("");
    setResult(null);
    setError(null);
    setIsSubmitting(false);
    setProgressStatus("idle");
    setActiveStageIndex(0);
  }

  function retryLiteRequest() {
    const retrySubmission = lastSubmission ?? { input: input.trim(), inputTypeHint };
    void runLiteRequest(retrySubmission);
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
                <div className="flex flex-wrap items-center justify-between gap-3">
                  {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : <span className="text-xs text-muted-foreground">Lite progress is local to this browser request.</span>}
                  <div className="flex gap-2">
                    {isSubmitting && (
                      <Button type="button" variant="destructive" size="sm" onClick={cancelLiteRequest}>
                        <XCircle className="h-4 w-4" aria-hidden="true" />
                        Cancel
                      </Button>
                    )}
                    {error && !isSubmitting && (
                      <Button type="button" variant="secondary" size="sm" onClick={retryLiteRequest}>
                        <RefreshCw className="h-4 w-4" aria-hidden="true" />
                        Retry
                      </Button>
                    )}
                    {(result || error || isSubmitting) && (
                      <Button type="button" variant="ghost" size="sm" onClick={clearLiteWorkspace}>
                        Clear
                      </Button>
                    )}
                  </div>
                </div>
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
              <div role="status" aria-live="polite" className="rounded-md border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
                {progressSummary}
              </div>
              <div role="progressbar" aria-label="Lite request progress" aria-valuemin={0} aria-valuemax={liteProgressStages.length} aria-valuenow={progressValue(progressStatus, activeStageIndex)} className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(progressValue(progressStatus, activeStageIndex) / liteProgressStages.length) * 100}%` }} />
              </div>
              {liteProgressStages.map((stage, index) => {
                const stageStatus = liteStageStatus(progressStatus, activeStageIndex, index);
                return (
                  <div key={stage.id} className="flex items-start gap-3 rounded-md border bg-white px-3 py-2">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-primary">
                      <LiteStageIcon status={stageStatus} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{stage.label}</span>
                      <span className="block text-xs leading-5 text-muted-foreground">{stage.description}</span>
                    </span>
                    <Badge tone={toneForStageStatus(stageStatus)}>{labelForStageStatus(stageStatus)}</Badge>
                  </div>
                );
              })}
              <p className="text-xs leading-5 text-muted-foreground">
                Lite Mode uses optimistic request-local progress while one server-side answer request returns the final typed response.
              </p>
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

  if (isLiteReportResponse(result)) {
    return <ReportWorkspace data={liteResponseToReportWorkspace(result)} />;
  }

  return null;
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

function LiteStageIcon({ status }: { status: LiteStageStatus }) {
  if (status === "active") return <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />;
  if (status === "complete") return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />;
  if (status === "failed" || status === "cancelled") return <XCircle className="h-4 w-4" aria-hidden="true" />;
  return <Circle className="h-4 w-4" aria-hidden="true" />;
}

function liteStageStatus(
  progressStatus: LiteProgressStatus,
  activeStageIndex: number,
  stageIndex: number,
): LiteStageStatus {
  if (progressStatus === "success") return "complete";
  if (progressStatus === "failure" && stageIndex === activeStageIndex) return "failed";
  if (progressStatus === "cancelled" && stageIndex === activeStageIndex) return "cancelled";
  if (progressStatus === "failure" || progressStatus === "cancelled") {
    return stageIndex < activeStageIndex ? "complete" : "queued";
  }
  if (progressStatus === "loading") {
    if (stageIndex < activeStageIndex) return "complete";
    if (stageIndex === activeStageIndex) return "active";
  }
  return "queued";
}

function labelForStageStatus(status: LiteStageStatus) {
  if (status === "active") return "Active";
  if (status === "complete") return "Ready";
  if (status === "failed") return "Needs retry";
  if (status === "cancelled") return "Cancelled";
  return "Queued";
}

function toneForStageStatus(status: LiteStageStatus) {
  if (status === "active") return "info";
  if (status === "complete") return "support";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "warning";
  return "neutral";
}

function progressValue(progressStatus: LiteProgressStatus, activeStageIndex: number) {
  if (progressStatus === "success") return liteProgressStages.length;
  if (progressStatus === "idle") return 0;
  return Math.min(activeStageIndex + 1, liteProgressStages.length);
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

function createClientTraceId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `lite-${Date.now()}`;
}
