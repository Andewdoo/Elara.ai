"use client";

import {
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  FileText,
  FileWarning,
  Info,
  PanelRightClose,
  PanelRightOpen,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { ReportHeaderActions } from "@/components/report/report-actions";
import { ScoreCharts } from "@/components/report/score-charts";
import { SourceGraph } from "@/components/report/source-graph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunId } from "@/components/ui/run-id";
import { evidenceCategoryForStance, groupEvidenceByStance, type EvidenceCategory } from "@/lib/report-evidence";
import type { EvidenceStance, ReportWorkspaceData, SourceRecord } from "@/lib/report-types";
import { cn } from "@/lib/utils";
import { useReportUiStore, type ReportTab } from "@/stores/report-ui-store";

const tabs: Array<{ id: ReportTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "claims", label: "Claims" },
  { id: "evidence", label: "Evidence" },
  { id: "graph", label: "Graph" },
];

const reportDateTimeFormat = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function ReportWorkspace({ data }: { data: ReportWorkspaceData }) {
  return <ReportWorkspaceContent key={data.run.run_id} data={data} />;
}

function ReportWorkspaceContent({ data }: { data: ReportWorkspaceData }) {
  const { run, report, sources, sourceGraph, mode = "full" } = data;
  const isLite = mode === "lite";
  const ui = useReportUiStore();
  const [activeReportTab, setActiveReportTab] = useState<ReportTab>("overview");
  const openTab = (tab: ReportTab) => {
    setActiveReportTab(tab);
    ui.setActiveReportTab(tab);
  };
  const selectedClaim = report.atomic_claims.find((claim) => claim.id === ui.selectedClaimId) ?? report.atomic_claims[0];
  const selectedSource = sources.find((source) => source.id === ui.selectedSourceId) ?? sources[0];
  const selectedPassage = selectedSource?.passages.find((passage) => passage.id === ui.selectedEvidenceId)
    ?? selectedSource?.passages.find((passage) => passage.citations.length)
    ?? selectedSource?.passages[0];
  const evidenceByStance = groupEvidenceByStance(report.evidence);
  const openEvidence = (passageId: string, sourceUrl: string) => {
    const source = sources.find((item) => item.canonical_url === sourceUrl || item.passages.some((passage) => passage.id === passageId));
    if (source) ui.selectSource(source.id);
    ui.selectEvidence(passageId);
  };
  const reviewed = formatReportDateTime(report.evidence_reviewed_at);
  const generated = formatReportDateTime(report.generated_at);
  const summarySentences = report.report_sentences.filter((sentence) => sentence.report_section === "summary");
  const factualSentences = report.report_sentences.filter((sentence) => sentence.report_section === "factual_finding");
  const attributionSentences = report.report_sentences.filter((sentence) => sentence.report_section === "attribution");
  const contradictionSentences = report.report_sentences.filter((sentence) => sentence.report_section === "strongest_contradiction");
  const inaccessibleCount = sources.filter((source) => source.access_status !== "FETCHED").length;
  const showSourceDrawer = activeReportTab !== "graph" && ui.sourceDrawerOpen;
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!direction && !["Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + direction + tabs.length) % tabs.length;
    openTab(tabs[nextIndex].id);
    document.getElementById(`report-tab-${tabs[nextIndex].id}`)?.focus();
  };

  return (
    <div className="report-ledger grid min-w-0 gap-0 overflow-hidden border-y bg-background text-foreground sm:rounded-md sm:border">
      <header className="grid min-w-0 gap-6 border-b bg-card px-4 py-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(270px,0.42fr)] lg:px-8 lg:py-7">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[0.7rem] uppercase tracking-[0.08em]">
            <Badge className="gap-1.5 border border-primary/30 bg-primary/10 text-primary" tone="neutral">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
              {run.status}
            </Badge>
            <Badge className="border border-accent/70 bg-accent/10 text-accent-foreground" tone="neutral">{run.research_depth}</Badge>
            {isLite && <Badge className="border border-border bg-muted text-foreground" tone="neutral">Curated Lite library</Badge>}
          </div>
          <h1 className="mt-4 max-w-4xl font-editorial text-3xl font-semibold leading-[1.08] tracking-[-0.025em] sm:text-4xl">
            {run.title ?? "Verification report"}
          </h1>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[0.7rem] leading-5 text-muted-foreground">
            <span>Reviewed: {reviewed}</span>
            <span aria-hidden="true" className="hidden sm:inline">/</span>
            <span>Generated: {generated}</span>
          </div>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
            Evidence reviewed as of {reviewed}. New evidence or corrections may change this assessment.
          </p>
          {report.workspace_scope && <p className="mt-2 max-w-3xl text-xs leading-5 text-muted-foreground">{report.workspace_scope}</p>}
          <div className="mt-auto pt-2"><RunId value={run.run_id} className="font-mono" /></div>
        </div>

        <div className="grid content-start gap-4 border-t pt-5 lg:border-l lg:border-t-0 lg:pl-7 lg:pt-0">
          <div>
            <span className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-muted-foreground">{isLite ? "Lite result" : "Verdict"}</span>
            <div className="mt-2 flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-6 w-6 shrink-0 text-primary" strokeWidth={1.6} aria-hidden="true" />
              <p className="font-mono text-base font-semibold uppercase leading-6 text-foreground">{report.verdict ?? "Not verified"}</p>
            </div>
          </div>
          <dl className="grid grid-cols-3 border-y py-3 font-mono text-center text-[0.68rem] text-muted-foreground">
            <Metric label="Claims" value={report.atomic_claims.length} />
            <Metric label="Evidence" value={report.evidence.length} className="border-x" />
            <Metric label="Unavailable" value={inaccessibleCount} />
          </dl>
          {run.is_owner && <ReportHeaderActions runId={run.run_id} saved={Boolean(run.saved_at)} />}
        </div>
      </header>

      <div className="sticky top-0 z-20 flex min-w-0 items-center border-b bg-card">
        <nav role="tablist" className="flex min-w-0 flex-1 overflow-x-auto px-2 sm:px-5" aria-label="Report sections">
          {tabs.map((tab, index) => (
            <button
              type="button"
              role="tab"
              id={`report-tab-${tab.id}`}
              aria-selected={activeReportTab === tab.id}
              aria-controls={`report-panel-${tab.id}`}
              tabIndex={activeReportTab === tab.id ? 0 : -1}
              key={tab.id}
              className={cn(
                "relative min-h-12 shrink-0 cursor-pointer px-4 font-editorial text-base outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none",
                activeReportTab === tab.id ? "text-foreground after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-primary" : "text-muted-foreground hover:text-foreground",
              )}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              onClick={() => openTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        {activeReportTab !== "graph" && (
          <Button
            className="mr-3 hidden h-11 min-w-11 xl:inline-flex"
            size="icon"
            variant="ghost"
            aria-label={ui.sourceDrawerOpen ? "Close source drawer" : "Open source drawer"}
            onClick={() => ui.setSourceDrawerOpen(!ui.sourceDrawerOpen)}
          >
            {ui.sourceDrawerOpen ? <PanelRightClose className="h-4 w-4" aria-hidden="true" /> : <PanelRightOpen className="h-4 w-4" aria-hidden="true" />}
          </Button>
        )}
      </div>

      <div className={cn("grid min-w-0 items-start bg-card", showSourceDrawer ? "xl:grid-cols-[260px_minmax(0,1fr)_340px]" : "xl:grid-cols-[260px_minmax(0,1fr)]")}>
        <aside className="hidden self-stretch border-r bg-card xl:block">
          <ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim} />
        </aside>

        <main
          role="tabpanel"
          id={`report-panel-${activeReportTab}`}
          aria-labelledby={`report-tab-${activeReportTab}`}
          tabIndex={0}
          className="grid min-w-0 content-start gap-5 bg-card p-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:p-6"
        >
          {activeReportTab === "overview" && (
            <>
              <section aria-labelledby="report-overview-heading" className="min-w-0">
                <div className="mb-6 flex items-start justify-between gap-4 border-b pb-4">
                  <div>
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-primary">Citation-audited record</p>
                    <h2 id="report-overview-heading" className="mt-1 font-editorial text-3xl font-semibold tracking-[-0.02em]">Report overview</h2>
                  </div>
                  <FileText className="mt-1 h-5 w-5 text-muted-foreground" strokeWidth={1.5} aria-hidden="true" />
                </div>
                <div className="grid gap-7">
                  {report.answer_markdown && (
                    <section className="grid gap-2">
                      <h3 className="font-editorial text-xl font-semibold">Cited answer</h3>
                      <div className="border-l-2 border-primary bg-muted/60 px-4 py-3 text-sm leading-7 whitespace-pre-wrap">{report.answer_markdown}</div>
                    </section>
                  )}
                  <SentenceSection title="Summary" sentences={summarySentences} empty="No citation-audited summary sentences were stored." onOpen={openEvidence} />
                  <SentenceSection title="Factual findings" sentences={factualSentences} empty="No separate factual findings were stored." onOpen={openEvidence} />
                  <SentenceSection title="Attribution findings" sentences={attributionSentences} empty="No attribution finding applies to this report." onOpen={openEvidence} />
                  <SentenceSection title="Strongest credible contradiction" sentences={contradictionSentences} empty="No credible contradiction was identified in the reviewed evidence." onOpen={openEvidence} emphasis="contradiction" />
                  <SpecializedPanels report={report} />
                  <section>
                    <h3 className="font-editorial text-xl font-semibold">Limitations</h3>
                    <div className="mt-3 grid gap-2">
                      {report.limitations.length ? report.limitations.map((item, index) => <p key={`${item}-${index}`} className="flex gap-3 border-l-2 border-accent bg-accent/10 px-4 py-3 text-sm leading-6"><Info className="mt-1 h-4 w-4 shrink-0 text-accent-foreground" aria-hidden="true" />{item}</p>) : <p className="border border-dashed p-4 text-sm text-muted-foreground">No limitations were recorded.</p>}
                    </div>
                  </section>
                </div>
              </section>
              {!isLite && <ScoreCharts report={report} />}
            </>
          )}

          {activeReportTab === "claims" && <ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim} detailed />}

          {activeReportTab === "evidence" && (
            <Card className="overflow-hidden rounded-sm shadow-none">
              <CardHeader className="flex flex-row items-center justify-between gap-3 bg-muted/40">
                <div>
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-primary">Reviewed record</p>
                  <CardTitle className="mt-1 font-editorial text-2xl">Evidence passages</CardTitle>
                </div>
                <label className="grid gap-1 font-mono text-[0.65rem] uppercase tracking-wide text-muted-foreground">
                  Evidence filter
                  <select className="min-h-11 rounded-sm border bg-card px-3 text-sm font-sans normal-case tracking-normal text-foreground" value={ui.evidenceFilter} onChange={(event) => ui.setEvidenceFilter(event.target.value as typeof ui.evidenceFilter)}>
                    <option value="all">All evidence</option>
                    <option value="supporting">Supporting</option>
                    <option value="contradicting">Contradicting</option>
                    <option value="neutral">Neutral</option>
                    <option value="inaccessible">Inaccessible</option>
                  </select>
                </label>
              </CardHeader>
              <CardContent className="grid gap-4 p-4 sm:p-5">
                {ui.evidenceFilter === "inaccessible" ? <InaccessibleSources sources={sources} onSelect={ui.selectSource} /> : <>
                  {evidenceByStance.invalid.length > 0 && <EvidenceContractError items={evidenceByStance.invalid} />}
                  {(evidenceByStance.invalid.length < report.evidence.length || report.evidence.length === 0) && <EvidenceColumns groups={evidenceByStance.groups} filter={ui.evidenceFilter} onOpen={openEvidence} mode={mode} />}
                </>}
              </CardContent>
            </Card>
          )}

          {activeReportTab === "graph" && (
            <Card className="overflow-hidden rounded-sm shadow-none">
              <CardHeader className="bg-muted/40">
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-primary">Relationship view</p>
                <CardTitle className="mt-1 font-editorial text-2xl">Source dependency graph</CardTitle>
              </CardHeader>
              <CardContent className="p-4 sm:p-5"><SourceGraph graph={sourceGraph} claims={report.atomic_claims} onSourceSelect={ui.selectSource} /></CardContent>
            </Card>
          )}
        </main>

        {showSourceDrawer && <SourceDrawer mode={mode} mobileOpen={Boolean(ui.selectedSourceId)} source={selectedSource} passage={selectedPassage} onClose={() => ui.setSourceDrawerOpen(false)} onPassage={ui.selectEvidence} />}
      </div>
    </div>
  );
}

function Metric({ label, value, className }: { label: string; value: number; className?: string }) {
  return <div className={cn("grid gap-1 px-2", className)}><dt className="uppercase tracking-wide">{label}</dt><dd className="text-base font-semibold tabular-nums text-foreground">{value}</dd></div>;
}

function SentenceSection({ title, sentences, empty, onOpen, emphasis = "default" }: { title: string; sentences: ReportWorkspaceData["report"]["report_sentences"]; empty: string; onOpen: (passageId: string, sourceUrl: string) => void; emphasis?: "default" | "contradiction" }) {
  return (
    <section className="grid gap-3">
      <h3 className="font-editorial text-xl font-semibold">{title}</h3>
      {sentences.length > 0 ? (
        <div className={cn("grid divide-y border-y", emphasis === "contradiction" && "border-destructive/40")}>
          {sentences.map((sentence, index) => (
            <button
              type="button"
              key={sentence.id}
              className="group flex min-h-12 cursor-pointer items-start gap-3 px-1 py-3 text-left text-sm leading-6 outline-none transition-colors duration-200 hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
              onClick={() => onOpen(sentence.passage_id, "")}
            >
              <span className={cn("mt-0.5 inline-flex h-6 min-w-6 shrink-0 items-center justify-center border font-mono text-[0.65rem]", emphasis === "contradiction" ? "border-destructive/50 text-destructive" : "border-border text-primary")}>{index + 1}</span>
              <span className="min-w-0 flex-1">{sentence.sentence_text}</span>
              <span className="mt-1 hidden shrink-0 font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground sm:block">Citation {sentence.audit_status}</span>
              <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : <p className="border border-dashed p-4 text-sm text-muted-foreground">{empty}</p>}
    </section>
  );
}

function InaccessibleSources({ sources, onSelect }: { sources: SourceRecord[]; onSelect: (id: string | null) => void }) {
  const inaccessible = sources.filter((source) => source.access_status !== "FETCHED");
  return <>{inaccessible.map((source) => <button type="button" key={source.id} onClick={() => onSelect(source.id)} className="min-h-11 cursor-pointer border border-accent/50 bg-accent/10 p-4 text-left outline-none transition-colors duration-200 hover:bg-accent/15 focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"><FileWarning className="inline h-4 w-4 text-accent-foreground" aria-hidden="true" /> <strong>{source.title ?? source.domain}</strong><p className="mt-1 text-sm leading-6">{source.inaccessible_reason ?? source.failure_reason ?? source.access_status}</p></button>)}{inaccessible.length === 0 && <p className="border border-dashed p-4 text-sm text-muted-foreground">No inaccessible sources were recorded.</p>}</>;
}

function ClaimRail({ claims, selectedId, onSelect, detailed = false }: { claims: ReportWorkspaceData["report"]["atomic_claims"]; selectedId?: string; onSelect: (id: string | null) => void; detailed?: boolean }) {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("all");
  const labels = [...new Set(claims.map((claim) => claim.final_label).filter((value): value is string => Boolean(value)))];
  const visible = claims.filter((claim) => (label === "all" || claim.final_label === label) && claim.claim_text.toLowerCase().includes(query.toLowerCase()));
  return (
    <section className={cn("grid min-w-0 content-start bg-card", detailed ? "border" : "sticky top-12 max-h-[calc(100dvh-3rem)]")}>
      <header className="border-b p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-editorial text-xl font-semibold">Atomic claims</h2>
          <span className="font-mono text-[0.65rem] text-muted-foreground">{visible.length}/{claims.length}</span>
        </div>
        <div className="mt-3 grid gap-2">
          <label className="relative">
            <span className="sr-only">Filter atomic claims</span>
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <input className="min-h-11 w-full min-w-0 rounded-sm border bg-card pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-ring/30" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search claims" aria-label="Filter atomic claims" />
          </label>
          <label className="relative">
            <span className="sr-only">Filter claims by label</span>
            <SlidersHorizontal className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <select className="min-h-11 w-full rounded-sm border bg-card pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-ring/30" value={label} onChange={(event) => setLabel(event.target.value)} aria-label="Filter claims by label">
              <option value="all">All labels ({claims.length})</option>
              {labels.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        </div>
      </header>
      <div className={cn("grid gap-2 p-2", !detailed && "overflow-y-auto")}>
        {visible.map((claim, index) => (
          <button
            type="button"
            key={claim.id}
            onClick={() => onSelect(claim.id)}
            aria-pressed={selectedId === claim.id}
            className={cn(
              "group grid min-h-11 cursor-pointer gap-3 border bg-card p-3 text-left outline-none transition-colors duration-200 hover:border-primary/70 focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none",
              selectedId === claim.id && "border-primary bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))]",
              detailed && "p-4 sm:p-5",
            )}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-6 min-w-6 items-center justify-center border font-mono text-[0.65rem] text-muted-foreground">{index + 1}</span>
                <Badge tone={claimLabelTone(claim.final_label)}>{claim.final_label ?? "Not verified"}</Badge>
              </div>
              <span className="font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground">Weight {claim.importance_weight}</span>
            </div>
            <span className={cn("font-editorial font-semibold leading-6", detailed ? "text-lg" : "text-base")}>{claim.claim_text}</span>
            <dl className="grid grid-cols-3 gap-2 border-t pt-2 font-mono text-[0.62rem] text-muted-foreground">
              <ClaimMetric label="Support" value={claim.support_score} />
              <ClaimMetric label="Confidence" value={claim.confidence_score} />
              <ClaimMetric label="Context" value={claim.context_completeness} />
            </dl>
            {detailed && [...claim.ambiguities, ...claim.gaps].map((gap, gapIndex) => <span key={`${gap}-${gapIndex}`} className="border-l-2 border-accent pl-3 text-sm leading-6 text-muted-foreground">{gap}</span>)}
          </button>
        ))}
        {visible.length === 0 && <p className="border border-dashed p-4 text-sm text-muted-foreground">No claims match these filters.</p>}
      </div>
    </section>
  );
}

function ClaimMetric({ label, value }: { label: string; value: number | null }) {
  return <div className="grid gap-0.5"><dt>{label}</dt><dd className="font-semibold tabular-nums text-foreground">{value ?? "-"}</dd></div>;
}

function claimLabelTone(label: string | null): "support" | "info" {
  const normalized = label?.toLowerCase() ?? "";
  return normalized.includes("support") && !normalized.startsWith("insufficient evidence") ? "support" : "info";
}

function EvidenceColumns({ groups, filter, onOpen, mode }: { groups: Record<EvidenceCategory, ReportWorkspaceData["report"]["evidence"]>; filter: "all" | EvidenceCategory; onOpen: (passageId: string, sourceUrl: string) => void; mode: ReportWorkspaceData["mode"] }) {
  const sections: Array<{ category: EvidenceCategory; title: string }> = [
    { category: "supporting", title: "Supporting evidence" },
    { category: "contradicting", title: "Contradicting evidence" },
    { category: "neutral", title: "Neutral evidence" },
  ];
  const visibleSections = filter === "all" ? sections : sections.filter((section) => section.category === filter);
  return <div className="grid gap-5 lg:grid-cols-2">{visibleSections.map((section) => <div key={section.category} className={cn(section.category === "neutral" && filter === "all" && "lg:col-span-2")}><EvidenceGroup title={section.title} items={groups[section.category]} onOpen={onOpen} mode={mode} /></div>)}</div>;
}

function EvidenceContractError({ items }: { items: ReportWorkspaceData["report"]["evidence"] }) {
  return <section role="alert" className="border border-destructive/50 bg-destructive/5 p-4 text-sm">
    <h3 className="font-editorial text-lg font-semibold">Evidence data needs review</h3>
    <p className="mt-1 leading-6">{items.length} stored evidence record{items.length === 1 ? " has" : "s have"} an unsupported stance value, so the report cannot safely present a classification.</p>
    <ul className="mt-3 grid gap-1 font-mono text-xs"><li>Expected API stances: STRONGLY_SUPPORTS, PARTIALLY_SUPPORTS, STRONGLY_CONTRADICTS, PARTIALLY_CONTRADICTS, or NEUTRAL.</li>{items.map((item) => <li key={item.id}>Record {item.id}: {String(item.stance)}</li>)}</ul>
  </section>;
}

function EvidenceGroup({ title, items, onOpen, mode }: { title: string; items: ReportWorkspaceData["report"]["evidence"]; onOpen: (passageId: string, sourceUrl: string) => void; mode: ReportWorkspaceData["mode"] }) {
  const isLite = mode === "lite";
  const isContradiction = title.startsWith("Contradicting");
  return (
    <section className="grid content-start gap-3">
      <div className="flex items-center justify-between border-b pb-2"><h3 className="font-editorial text-xl font-semibold">{title}</h3><span className="font-mono text-[0.65rem] text-muted-foreground">{items.length} records</span></div>
      {items.map((item, index) => (
        <button type="button" key={item.id} onClick={() => onOpen(item.passage_id, item.source_url)} className={cn("group grid min-h-11 cursor-pointer gap-3 border bg-card p-4 text-left outline-none transition-colors duration-200 hover:border-primary focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none", isContradiction && "hover:border-destructive")}>
          <div className="flex flex-wrap items-center gap-2"><span className="inline-flex h-6 min-w-6 items-center justify-center border font-mono text-[0.65rem]">{index + 1}</span><Badge tone={stanceTone(item.stance)}>{item.stance.replaceAll("_", " ")}</Badge></div>
          <p className="font-mono text-[0.66rem] leading-5 text-muted-foreground">{item.source_title ?? item.source_url} / {item.page_or_position ?? (isLite ? "stored Lite chunk" : "stored passage")}</p>
          <blockquote className={cn("border-l-2 pl-4 font-editorial text-base leading-7", isContradiction ? "border-destructive" : "border-primary")}>{item.passage_text}</blockquote>
          <span className="border-t pt-2 font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground">{isLite ? `Citation ${item.citation_status} / Lite evidence confidence ${item.adjusted_weight}%` : `Adjusted weight ${item.adjusted_weight} / Dependency ${item.dependency_multiplier} / Citation ${item.citation_status}`}</span>
        </button>
      ))}
      {items.length === 0 && <p className="border border-dashed p-4 text-sm text-muted-foreground">No evidence in this category.</p>}
    </section>
  );
}

function SpecializedPanels({ report }: { report: ReportWorkspaceData["report"] }) {
  const attribution = report.calculations.find((row) => row.formula_name === "attribution_support" && row.atomic_claim_id === null);
  const quote = report.calculations.find((row) => row.formula_name === "quote_fidelity" && row.atomic_claim_id === null);
  const context = report.calculations.find((row) => row.formula_name === "context_completeness" && row.atomic_claim_id === null);
  if (!attribution && !quote && !context) return null;
  return <div className="grid border md:grid-cols-3">{attribution && <ScorePanel title="Attribution support" record={attribution} />}{quote && <ScorePanel title="Quote fidelity" record={quote} />}{context && <ScorePanel title="Surrounding context" record={context} />}</div>;
}

function ScorePanel({ title, record }: { title: string; record: ReportWorkspaceData["report"]["calculations"][number] }) {
  return <div className="grid gap-2 border-b p-4 last:border-b-0 md:border-b-0 md:border-r md:last:border-r-0"><p className="font-mono text-[0.65rem] uppercase tracking-wide text-muted-foreground">{title}</p><p className="font-mono text-2xl font-semibold tabular-nums">{String(record.result.score ?? "Not scored")}</p></div>;
}

function SourceDrawer({ source, passage, mobileOpen, mode, onClose, onPassage }: { source?: SourceRecord; passage?: SourceRecord["passages"][number]; mobileOpen: boolean; mode: ReportWorkspaceData["mode"]; onClose: () => void; onPassage: (id: string | null) => void }) {
  const drawerRef = useRef<HTMLElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!mobileOpen || !drawerRef.current) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const drawer = drawerRef.current;
    const focusable = () => [...drawer.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')];
    focusable()[0]?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    drawer.addEventListener("keydown", onKeyDown);
    return () => { drawer.removeEventListener("keydown", onKeyDown); previousFocusRef.current?.focus(); };
  }, [mobileOpen, onClose]);
  const isLite = mode === "lite";
  if (!source) return <aside className="border-l bg-card p-5 text-sm text-muted-foreground">No sources were stored for this report.</aside>;
  return (
    <aside
      ref={drawerRef}
      role="dialog"
      aria-modal={mobileOpen}
      aria-labelledby="source-drawer-title"
      className={cn("fixed inset-0 z-50 overflow-y-auto bg-card p-4 sm:p-5 xl:static xl:z-auto xl:max-h-[calc(100dvh-3rem)] xl:min-h-0 xl:self-start xl:border-l", !mobileOpen && "hidden xl:block")}
    >
      <div className="flex items-start justify-between gap-3 border-b pb-4">
        <div className="min-w-0">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-primary">Source record</p>
          <h2 id="source-drawer-title" className="mt-1 font-editorial text-xl font-semibold leading-6">{source.title ?? source.domain}</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{source.publisher ?? source.author ?? source.domain}</p>
        </div>
        <Button className="h-11 min-w-11 shrink-0" size="icon" variant="ghost" onClick={onClose} aria-label="Close source drawer"><X className="h-4 w-4" aria-hidden="true" /></Button>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <Badge className="gap-1.5 border border-primary/30 bg-primary/10 text-primary" tone={source.access_status === "FETCHED" ? "support" : "warning"}>{source.access_status === "FETCHED" && <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />}{source.access_status}</Badge>
        {source.canonical_url ? <a className="inline-flex min-h-11 cursor-pointer items-center gap-1 text-sm font-medium text-primary underline decoration-primary/40 underline-offset-4" href={source.canonical_url} target="_blank" rel="noreferrer">Open source <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a> : null}
      </div>
      {!source.canonical_url && <p className="mt-3 text-xs leading-5 text-muted-foreground">Stored curated Lite source metadata only; no public source URL was provided.</p>}

      <dl className="mt-4 grid border-y py-2 text-xs">
        {[["Role", source.role], ["Type", source.source_type], ["Published", source.published_at ? formatReportDateTime(source.published_at) : "Unavailable"], ["Retrieved", source.retrieved_at ? formatReportDateTime(source.retrieved_at) : "Unavailable"], ["Correction", source.correction_status ?? "None recorded"]].map(([key, value]) => <div key={key} className="grid grid-cols-[88px_1fr] gap-3 py-1.5"><dt className="font-mono text-muted-foreground">{key}</dt><dd className="break-words">{value}</dd></div>)}
      </dl>

      <details className="border-b py-4 text-xs" open={source.correction_history.length > 0}>
        <summary className="min-h-11 cursor-pointer py-2 font-semibold">Correction history ({source.correction_history.length})</summary>
        {source.correction_history.length ? source.correction_history.map((item) => <p key={item.snapshot_id} className="mt-2 border-l-2 border-accent pl-3 leading-5">Snapshot v{item.snapshot_version}: {item.status} / {formatReportDateTime(item.retrieved_at)}</p>) : <p className="mt-1 text-muted-foreground">No correction notices were recorded.</p>}
      </details>

      <div className="mt-4 grid gap-3">
        <div className="flex items-end justify-between gap-2"><h3 className="font-editorial text-lg font-semibold">{isLite ? "Exact source chunk - Cited sentences" : "Exact passage - Cited passages"}</h3>{passage && source.passages.length > 0 && <span className="shrink-0 font-mono text-[0.62rem] text-muted-foreground">{source.passages.findIndex((item) => item.id === passage.id) + 1} of {source.passages.length}</span>}</div>
        {passage ? (
          <>
            <blockquote className="border-l-2 border-primary bg-muted/50 p-4 font-editorial text-base italic leading-7">{passage.text}</blockquote>
            <p className="font-mono text-[0.62rem] leading-5 text-muted-foreground">{passage.heading_path ?? "No heading"} / {passage.page_or_position ?? `paragraph ${passage.paragraph_index ?? "unrecorded"}`} / {isLite ? "retrieval confidence" : "extraction"} {Math.round(passage.extraction_certainty * 100)}%</p>
            {(passage.speaker || passage.table_ref) && <p className="text-xs text-muted-foreground">Speaker: {passage.speaker ?? "not recorded"} / Table: {passage.table_ref ?? "not recorded"}</p>}
            <div className="grid gap-2">
              {passage.citations.map((citation) => <div key={citation.id} className="border p-3 text-xs leading-5"><div className="flex items-center justify-between gap-2"><strong>{citation.report_section.replaceAll("_", " ")}</strong><span className="inline-flex items-center gap-1 font-mono uppercase text-primary"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />{citation.audit_status}</span></div><p className="mt-2">{citation.sentence_text}</p>{citation.audit_note && <p className="mt-2 text-muted-foreground">{citation.audit_note}</p>}</div>)}
            </div>
          </>
        ) : <p className="border border-dashed p-4 text-xs text-muted-foreground">No stored passage is available.</p>}

        {source.passages.length > 1 && (
          <label className="grid gap-1.5 font-mono text-[0.65rem] uppercase tracking-wide text-muted-foreground">
            Passage selector
            <select className="min-h-11 rounded-sm border bg-card px-3 font-sans text-sm normal-case tracking-normal text-foreground" value={passage?.id ?? ""} onChange={(event) => onPassage(event.target.value)} aria-label="Select source passage">
              {source.passages.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.page_or_position ?? item.heading_path ?? item.id}</option>)}
            </select>
          </label>
        )}
      </div>
    </aside>
  );
}

function stanceTone(stance: EvidenceStance) {
  const category = evidenceCategoryForStance(stance);
  return category === "supporting" ? "support" : category === "contradicting" ? "danger" : "neutral";
}

function formatReportDateTime(value: string) {
  return `${reportDateTimeFormat.format(new Date(value))} UTC`;
}
