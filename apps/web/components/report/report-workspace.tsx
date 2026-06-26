"use client";

import { AlertTriangle, Calculator, CheckCircle2, Database, FileWarning, GitBranch, Info, ListFilter, MessageSquareWarning, PanelRightClose, PanelRightOpen } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScoreCharts } from "@/components/report/score-charts";
import { SourceGraph } from "@/components/report/source-graph";
import { mockedReport } from "@/lib/mock-report";
import type { EvidenceItemRecord, ReportRecord } from "@/lib/report-types";
import { useReportUiStore, type ReportTab } from "@/stores/report-ui-store";
import { cn } from "@/lib/utils";

const tabs: Array<{ id: ReportTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "claims", label: "Claims" },
  { id: "evidence", label: "Evidence" },
  { id: "graph", label: "Graph" },
  { id: "calculations", label: "Calculations" },
  { id: "methodology", label: "Methodology" },
];

function stanceTone(stance: EvidenceItemRecord["stance"]) {
  if (stance.includes("SUPPORTS")) return "support";
  if (stance.includes("CONTRADICTS")) return "danger";
  return "neutral";
}

export function ReportWorkspace({ runId, report = mockedReport }: { runId: string; report?: ReportRecord }) {
  const {
    activeReportTab,
    evidenceFilter,
    selectedClaimId,
    selectedSourceId,
    sourceDrawerOpen,
    selectClaim,
    selectSource,
    setActiveReportTab,
    setEvidenceFilter,
    setSourceDrawerOpen,
  } = useReportUiStore();

  const selectedClaim = report.atomicClaims.find((claim) => claim.id === selectedClaimId) ?? report.atomicClaims[0];
  const selectedSource = report.sources.find((source) => source.id === selectedSourceId) ?? report.sources[0];
  const selectedSourceEvidence = report.evidenceItems.filter((item) => item.sourceId === selectedSource.id);
  const filteredEvidence = report.evidenceItems.filter((item) => {
    if (evidenceFilter === "supporting") return item.stance.includes("SUPPORTS");
    if (evidenceFilter === "contradicting") return item.stance.includes("CONTRADICTS");
    if (evidenceFilter === "inaccessible") return false;
    return true;
  });

  return (
    <div className="grid gap-4">
      <section className="grid gap-3 rounded-lg border bg-white p-4 shadow-subtle lg:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="support">{report.status}</Badge>
            <Badge tone="info">{report.researchDepth}</Badge>
            <span className="text-xs text-muted-foreground">Run {runId}</span>
          </div>
          <h1 className="mt-3 text-2xl font-semibold tracking-normal">{report.title}</h1>
          <p className="mt-2 max-w-4xl text-sm text-muted-foreground">{report.evidenceTimestampText}</p>
        </div>
        <div className="grid min-w-60 gap-2 rounded-md border bg-muted/40 p-3">
          <span className="text-xs font-medium text-muted-foreground">Verdict</span>
          <span className="text-lg font-semibold">{report.verdict}</span>
        </div>
      </section>

      <div className="flex gap-2 overflow-x-auto rounded-lg border bg-white p-2">
        {tabs.map((tab) => (
          <Button
            key={tab.id}
            size="sm"
            variant={activeReportTab === tab.id ? "primary" : "ghost"}
            onClick={() => setActiveReportTab(tab.id)}
          >
            {tab.label}
          </Button>
        ))}
        <Button
          className="ml-auto"
          size="icon"
          variant="ghost"
          aria-label={sourceDrawerOpen ? "Close source drawer" : "Open source drawer"}
          onClick={() => setSourceDrawerOpen(!sourceDrawerOpen)}
        >
          {sourceDrawerOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
        </Button>
      </div>

      <div className={cn("grid gap-4", sourceDrawerOpen ? "xl:grid-cols-[260px_1fr_320px]" : "xl:grid-cols-[260px_1fr]")}>
        <aside className="grid gap-3 self-start">
          <Card>
            <CardHeader>
              <CardTitle>Atomic claims</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              {report.atomicClaims.map((claim) => (
                <button
                  key={claim.id}
                  className={cn(
                    "grid gap-2 rounded-md border bg-white p-3 text-left transition hover:border-primary/50",
                    selectedClaim.id === claim.id && "border-primary bg-secondary/60",
                  )}
                  onClick={() => selectClaim(claim.id)}
                >
                  <span className="text-xs font-semibold">{claim.finalLabel}</span>
                  <span className="text-sm">{claim.claimText}</span>
                  <span className="text-xs text-muted-foreground">Support {claim.supportScore} - Confidence {claim.confidenceScore}</span>
                </button>
              ))}
            </CardContent>
          </Card>
        </aside>

        <section className="grid gap-4">
          {activeReportTab === "overview" && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Report overview</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4">
                  <p className="text-sm leading-6">{report.verdictSummary}</p>
                  <div className="grid gap-3 md:grid-cols-4">
                    {report.scoreRecords.map((score) => (
                      <div key={score.key} className="rounded-md border bg-white p-3">
                        <span className="block text-xs text-muted-foreground">{score.label}</span>
                        <span className="mt-1 block text-2xl font-semibold">{score.value}</span>
                        <span className="block text-xs text-muted-foreground">from {score.calculationId}</span>
                      </div>
                    ))}
                  </div>
                  <FeedbackControls />
                  <div className="grid gap-2">
                    <span className="text-sm font-semibold">Limitations</span>
                    {report.limitations.map((limitation) => (
                      <div key={limitation} className="flex gap-2 rounded-md bg-muted p-3 text-sm">
                        <Info className="mt-0.5 h-4 w-4 text-primary" aria-hidden="true" />
                        {limitation}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <ScoreCharts report={report} />
            </>
          )}

          {activeReportTab === "claims" && (
            <Card>
              <CardHeader>
                <CardTitle>Claim detail</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4">
                {report.atomicClaims.map((claim) => (
                  <div key={claim.id} className="grid gap-3 rounded-md border bg-white p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={claim.finalLabel === "Supported" ? "support" : claim.finalLabel === "Not verified" ? "warning" : "info"}>
                        {claim.finalLabel}
                      </Badge>
                      <span className="text-xs text-muted-foreground">Weight {claim.importanceWeight}</span>
                      <span className="text-xs text-muted-foreground">{claim.claimType}</span>
                    </div>
                    <p className="font-medium">{claim.claimText}</p>
                    <div className="grid gap-2 md:grid-cols-3">
                      <Meter label="Support" value={claim.supportScore} />
                      <Meter label="Confidence" value={claim.confidenceScore} />
                      <Meter label="Context" value={claim.contextCompleteness} />
                    </div>
                    {claim.gaps.map((gap) => (
                      <p key={gap} className="text-sm text-muted-foreground">{gap}</p>
                    ))}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {activeReportTab === "evidence" && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-3">
                <CardTitle>Evidence</CardTitle>
                <div className="flex items-center gap-2">
                  <ListFilter className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  <select
                    className="rounded-md border bg-white px-2 py-1 text-xs"
                    value={evidenceFilter}
                    onChange={(event) => setEvidenceFilter(event.target.value as typeof evidenceFilter)}
                  >
                    <option value="all">All</option>
                    <option value="supporting">Supporting</option>
                    <option value="contradicting">Contradicting</option>
                    <option value="inaccessible">Inaccessible</option>
                  </select>
                </div>
              </CardHeader>
              <CardContent className="grid gap-3">
                {evidenceFilter === "inaccessible"
                  ? report.inaccessibleSources.map((source) => (
                      <div key={source.id} className="rounded-md border border-amber-200 bg-amber-50 p-3">
                        <div className="flex items-center gap-2">
                          <FileWarning className="h-4 w-4 text-amber-700" aria-hidden="true" />
                          <span className="font-semibold">{source.title}</span>
                        </div>
                        <p className="mt-2 text-sm text-amber-900">{source.inaccessibleReason}</p>
                      </div>
                    ))
                  : filteredEvidence.map((item) => {
                      const source = report.sources.find((sourceRecord) => sourceRecord.id === item.sourceId);
                      return (
                        <div key={item.id} className="grid gap-3 rounded-md border bg-white p-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={stanceTone(item.stance)}>{item.stance.replaceAll("_", " ")}</Badge>
                            <span className="text-xs text-muted-foreground">{source?.publisher}</span>
                            <span className="text-xs text-muted-foreground">{item.passageLocator}</span>
                          </div>
                          <blockquote className="border-l-4 border-primary pl-3 text-sm leading-6">{item.excerpt}</blockquote>
                          <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                            <span>Weight {item.adjustedWeight}</span>
                            <span>Dependency {item.quality.dependencyMultiplier}</span>
                            <span>Citation {item.citationStatus}</span>
                          </div>
                        </div>
                      );
                    })}
              </CardContent>
            </Card>
          )}

          {activeReportTab === "graph" && (
            <Card>
              <CardHeader>
                <CardTitle>Source dependency graph</CardTitle>
              </CardHeader>
              <CardContent>
                <SourceGraph report={report} onSourceSelect={selectSource} />
              </CardContent>
            </Card>
          )}

          {activeReportTab === "calculations" && (
            <Card>
              <CardHeader>
                <CardTitle>Calculation audit</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                {report.calculations.map((calculation) => (
                  <div key={calculation.id} className="grid gap-2 rounded-md border bg-white p-4">
                    <div className="flex items-center gap-2">
                      <Calculator className="h-4 w-4 text-primary" aria-hidden="true" />
                      <span className="font-semibold">{calculation.formulaName}</span>
                      <Badge tone={calculation.auditStatus === "passed" ? "support" : "warning"}>{calculation.auditStatus}</Badge>
                    </div>
                    <code className="rounded-md bg-muted px-2 py-1 text-xs">{calculation.formulaText}</code>
                    <div className="grid gap-2 text-xs md:grid-cols-3">
                      <pre className="overflow-auto rounded-md bg-muted p-2">{JSON.stringify(calculation.inputs, null, 2)}</pre>
                      <pre className="overflow-auto rounded-md bg-muted p-2">{JSON.stringify(calculation.result, null, 2)}</pre>
                      <pre className="overflow-auto rounded-md bg-muted p-2">{JSON.stringify(calculation.decimalContext, null, 2)}</pre>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {activeReportTab === "methodology" && (
            <Card>
              <CardHeader>
                <CardTitle>Methodology and versions</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4">
                <VersionGrid title="Run versions" values={report.methodology} />
                <VersionGrid title="Prompts" values={report.methodology.promptVersions} />
                <VersionGrid title="Models" values={report.methodology.modelVersions} />
                <VersionGrid title="Parsers" values={report.methodology.parserVersions} />
              </CardContent>
            </Card>
          )}
        </section>

        {sourceDrawerOpen && (
          <aside className="grid gap-3 self-start">
            <Card>
              <CardHeader>
                <CardTitle>Source drawer</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="grid gap-3 rounded-md border border-primary/40 bg-secondary/60 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-semibold">{selectedSource.title}</span>
                    <Badge tone={selectedSource.accessStatus === "FETCHED" ? "support" : "warning"}>{selectedSource.accessStatus}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {selectedSource.publisher} - {selectedSource.domain}
                  </p>
                  <dl className="grid gap-1 text-xs text-muted-foreground">
                    <div className="flex justify-between gap-3">
                      <dt>Retrieved</dt>
                      <dd>{selectedSource.retrievedAt ? new Date(selectedSource.retrievedAt).toLocaleString() : "Unavailable"}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt>Snapshot</dt>
                      <dd>{selectedSource.snapshotId ?? "Unavailable"}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt>Parser</dt>
                      <dd>{selectedSource.parserName ? `${selectedSource.parserName} ${selectedSource.parserVersion}` : "Not parsed"}</dd>
                    </div>
                  </dl>
                  {selectedSourceEvidence.length > 0 ? (
                    <div className="grid gap-2">
                      <span className="text-xs font-semibold">Cited passages</span>
                      {selectedSourceEvidence.map((item) => (
                        <blockquote key={item.id} className="rounded-md bg-white p-2 text-xs leading-5">
                          <span className="block font-medium">{item.passageLocator}</span>
                          {item.excerpt}
                        </blockquote>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">{selectedSource.inaccessibleReason ?? "No cited passage selected for this source."}</p>
                  )}
                </div>
                {report.sources.map((source) => (
                  <button
                    key={source.id}
                    className={cn(
                      "grid gap-2 rounded-md border bg-white p-3 text-left transition hover:border-primary/50",
                      source.id === selectedSource.id && "border-primary",
                    )}
                    onClick={() => selectSource(source.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm font-semibold">{source.title}</span>
                      <Badge tone={source.accessStatus === "FETCHED" ? "support" : "warning"}>{source.accessStatus}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground">{source.publisher} - {source.domain}</p>
                    <p className="text-xs">{source.retrievalReason}</p>
                    <dl className="grid gap-1 text-xs text-muted-foreground">
                      <div className="flex justify-between gap-3">
                        <dt>Snapshot</dt>
                        <dd>{source.snapshotId ?? "Unavailable"}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>Parser</dt>
                        <dd>{source.parserName ? `${source.parserName} ${source.parserVersion}` : "Not parsed"}</dd>
                      </div>
                    </dl>
                  </button>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Audit status</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 text-sm">
                <span className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-700" /> Citation presence checked</span>
                <span className="flex items-center gap-2"><GitBranch className="h-4 w-4 text-primary" /> Source dependency grouped</span>
                <span className="flex items-center gap-2"><Database className="h-4 w-4 text-sky-700" /> Snapshot ids retained</span>
                <span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-700" /> Inaccessible source preserved</span>
              </CardContent>
            </Card>
          </aside>
        )}
      </div>
    </div>
  );
}

function FeedbackControls() {
  return (
    <div className="grid gap-3 rounded-md border bg-white p-3">
      <div className="flex items-center gap-2">
        <MessageSquareWarning className="h-4 w-4 text-primary" aria-hidden="true" />
        <span className="text-sm font-semibold">Feedback and correction controls</span>
      </div>
      <div className="grid gap-2 md:grid-cols-[220px_1fr_auto]">
        <select className="rounded-md border bg-white px-3 py-2 text-sm" defaultValue="correction">
          <option value="correction">Correction</option>
          <option value="missed_evidence">Missed evidence</option>
          <option value="appeal">Appeal</option>
          <option value="broken_citation">Broken citation</option>
        </select>
        <input
          className="rounded-md border bg-white px-3 py-2 text-sm"
          placeholder="Describe the issue or source URL"
          aria-label="Feedback message"
        />
        <Button variant="secondary">Queue feedback</Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Mock-only control. The API step will persist feedback with run ownership checks.
      </p>
    </div>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-muted p-3">
      <div className="flex items-center justify-between text-xs">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-white">
        <div className="h-2 rounded-full bg-primary" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function VersionGrid({ title, values }: { title: string; values: Record<string, unknown> }) {
  return (
    <div className="grid gap-2 rounded-md border bg-white p-3">
      <span className="text-sm font-semibold">{title}</span>
      <dl className="grid gap-2 text-sm md:grid-cols-2">
        {Object.entries(values).map(([key, value]) =>
          typeof value === "string" ? (
            <div key={key} className="flex justify-between gap-3 rounded-md bg-muted px-3 py-2">
              <dt className="text-muted-foreground">{key}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ) : null,
        )}
      </dl>
    </div>
  );
}
