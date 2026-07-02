"use client";

import { Calculator, ExternalLink, FileWarning, Info, PanelRightClose, PanelRightOpen, X } from "lucide-react";
import { useState } from "react";

import { ScoreCharts } from "@/components/report/score-charts";
import { FeedbackControls, ReportHeaderActions } from "@/components/report/report-actions";
import { SourceGraph } from "@/components/report/source-graph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EvidenceStance, ReportWorkspaceData, SourceRecord } from "@/lib/report-types";
import { cn } from "@/lib/utils";
import { useReportUiStore, type ReportTab } from "@/stores/report-ui-store";

const tabs: Array<{ id: ReportTab; label: string }> = [
  { id: "overview", label: "Overview" }, { id: "claims", label: "Claims" },
  { id: "evidence", label: "Evidence" }, { id: "graph", label: "Graph" },
  { id: "calculations", label: "Calculations" }, { id: "methodology", label: "Methodology" },
];

export function ReportWorkspace({ data }: { data: ReportWorkspaceData }) {
  const { run, report, sources, sourceGraph } = data;
  const ui = useReportUiStore();
  const selectedClaim = report.atomic_claims.find((claim) => claim.id === ui.selectedClaimId) ?? report.atomic_claims[0];
  const selectedSource = sources.find((source) => source.id === ui.selectedSourceId) ?? sources[0];
  const selectedPassage = selectedSource?.passages.find((passage) => passage.id === ui.selectedEvidenceId) ?? selectedSource?.passages.find((passage) => passage.citations.length) ?? selectedSource?.passages[0];
  const evidence = report.evidence.filter((item) => {
    if (ui.selectedClaimId && item.atomic_claim_id !== ui.selectedClaimId) return false;
    if (ui.evidenceFilter === "supporting") return item.stance.includes("SUPPORTS");
    if (ui.evidenceFilter === "contradicting") return item.stance.includes("CONTRADICTS");
    return ui.evidenceFilter !== "inaccessible";
  });
  const openEvidence = (passageId: string, sourceUrl: string) => {
    const source = sources.find((item) => item.canonical_url === sourceUrl || item.passages.some((passage) => passage.id === passageId));
    if (source) ui.selectSource(source.id);
    ui.selectEvidence(passageId);
  };
  const reviewed = new Date(report.evidence_reviewed_at).toLocaleString();

  return <div className="grid gap-4">
    <header className="grid gap-3 rounded-lg border bg-white p-4 shadow-subtle lg:grid-cols-[1fr_auto]">
      <div><div className="flex flex-wrap items-center gap-2"><Badge tone={run.status === "COMPLETED" ? "support" : "info"}>{run.status}</Badge><Badge tone="info">{run.research_depth}</Badge><span className="text-xs text-muted-foreground">Run {run.run_id}</span></div><h1 className="mt-3 text-2xl font-semibold">{run.title ?? "Verification report"}</h1><p className="mt-2 text-sm text-muted-foreground">Evidence reviewed as of {reviewed}. New evidence or corrections may change this assessment.</p></div>
      <div className="grid min-w-60 gap-3"><div className="grid gap-1 rounded-md border bg-muted/40 p-3"><span className="text-xs text-muted-foreground">Verdict</span><span className="text-lg font-semibold">{report.verdict ?? "Not verified"}</span></div>{run.is_owner && <ReportHeaderActions runId={run.run_id} saved={Boolean(run.saved_at)} />}</div>
    </header>

    <nav className="flex gap-2 overflow-x-auto rounded-lg border bg-white p-2" aria-label="Report sections">
      {tabs.map((tab) => <Button key={tab.id} size="sm" variant={ui.activeReportTab === tab.id ? "primary" : "ghost"} onClick={() => ui.setActiveReportTab(tab.id)}>{tab.label}</Button>)}
      <Button className="ml-auto hidden xl:inline-flex" size="icon" variant="ghost" aria-label={ui.sourceDrawerOpen ? "Close source drawer" : "Open source drawer"} onClick={() => ui.setSourceDrawerOpen(!ui.sourceDrawerOpen)}>{ui.sourceDrawerOpen ? <PanelRightClose className="h-4 w-4"/> : <PanelRightOpen className="h-4 w-4"/>}</Button>
    </nav>

    <div className={cn("grid gap-4", ui.sourceDrawerOpen ? "xl:grid-cols-[260px_minmax(0,1fr)_340px]" : "xl:grid-cols-[260px_minmax(0,1fr)]")}>
      <aside className="hidden self-start xl:block"><ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim}/></aside>
      <main className="min-w-0 grid gap-4">
        {ui.activeReportTab === "overview" && <><Card><CardHeader><CardTitle>Report overview</CardTitle></CardHeader><CardContent className="grid gap-4">
          <div className="grid gap-2">{report.report_sentences.filter((sentence) => sentence.report_section.includes("summary")).map((sentence) => <button key={sentence.id} className="rounded-md border bg-white p-3 text-left text-sm leading-6 hover:border-primary" onClick={() => openEvidence(sentence.passage_id, "")}>{sentence.sentence_text}<span className="ml-2 text-xs text-muted-foreground">citation {sentence.audit_status}</span></button>)}{report.report_sentences.length === 0 && <p className="text-sm text-muted-foreground">No citation-audited summary sentences were stored.</p>}</div>
          <SpecializedPanels report={report}/>
          <div><p className="mb-2 text-sm font-semibold">Limitations</p>{report.limitations.length ? report.limitations.map((item) => <p key={item} className="mb-2 flex gap-2 rounded-md bg-muted p-3 text-sm"><Info className="mt-0.5 h-4 w-4 shrink-0 text-primary"/>{item}</p>) : <p className="text-sm text-muted-foreground">No limitations were recorded.</p>}</div>
          <section aria-label="Feedback and correction controls"><FeedbackControls runId={run.run_id} /></section>
        </CardContent></Card><ScoreCharts report={report}/></>}
        {ui.activeReportTab === "claims" && <ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim} detailed/>}
        {ui.activeReportTab === "evidence" && <Card><CardHeader><div className="flex items-center justify-between gap-3"><CardTitle>Evidence passages</CardTitle><select className="rounded-md border bg-white px-2 py-1 text-xs" value={ui.evidenceFilter} onChange={(event) => ui.setEvidenceFilter(event.target.value as typeof ui.evidenceFilter)}><option value="all">All</option><option value="supporting">Supporting</option><option value="contradicting">Contradicting</option><option value="inaccessible">Inaccessible</option></select></div></CardHeader><CardContent className="grid gap-3">
          {ui.evidenceFilter === "inaccessible" ? sources.filter((source) => source.access_status !== "FETCHED").map((source) => <button key={source.id} onClick={() => ui.selectSource(source.id)} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-left"><FileWarning className="inline h-4 w-4 text-amber-700"/> <strong>{source.title ?? source.domain}</strong><p className="mt-1 text-sm">{source.inaccessible_reason ?? source.failure_reason ?? source.access_status}</p></button>) : <EvidenceColumns items={evidence} onOpen={openEvidence}/>}
        </CardContent></Card>}
        {ui.activeReportTab === "graph" && <Card><CardHeader><CardTitle>Source dependency graph</CardTitle></CardHeader><CardContent><SourceGraph graph={sourceGraph} claims={report.atomic_claims} onSourceSelect={ui.selectSource}/></CardContent></Card>}
        {ui.activeReportTab === "calculations" && <Card><CardHeader><CardTitle>Server calculation records</CardTitle></CardHeader><CardContent className="grid gap-3">{report.calculations.map((row) => <article key={row.id} className="grid gap-2 rounded-md border p-4"><div className="flex items-center gap-2"><Calculator className="h-4 w-4 text-primary"/><strong>{row.formula_name}</strong><Badge tone={row.audit_status === "passed" ? "support" : "warning"}>{row.audit_status}</Badge></div><code className="rounded bg-muted p-2 text-xs">{row.formula_text}</code><div className="grid gap-2 md:grid-cols-3"><Json title="Inputs" value={row.inputs}/><Json title="Result" value={row.result}/><Json title="Decimal context" value={row.decimal_context}/></div></article>)}</CardContent></Card>}
        {ui.activeReportTab === "methodology" && <Card><CardHeader><CardTitle>Methodology and reproducibility</CardTitle></CardHeader><CardContent className="grid gap-3"><Version title="Methodology" value={{ methodology_version: report.methodology_version, workflow_version: report.workflow_version }}/><Version title="Models" value={report.model_versions}/><Version title="Prompts" value={report.prompt_versions}/><Version title="Parsers" value={report.parser_versions}/></CardContent></Card>}
      </main>
      {ui.sourceDrawerOpen && <SourceDrawer mobileOpen={Boolean(ui.selectedSourceId)} source={selectedSource} passage={selectedPassage} onClose={() => ui.setSourceDrawerOpen(false)} onPassage={ui.selectEvidence}/>}
    </div>
  </div>;
}

function ClaimRail({ claims, selectedId, onSelect, detailed = false }: { claims: ReportWorkspaceData["report"]["atomic_claims"]; selectedId?: string; onSelect: (id: string | null) => void; detailed?: boolean }) {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("all");
  const labels = [...new Set(claims.map((claim) => claim.final_label).filter((value): value is string => Boolean(value)))];
  const visible = claims.filter((claim) => (label === "all" || claim.final_label === label) && claim.claim_text.toLowerCase().includes(query.toLowerCase()));
  return <Card><CardHeader><CardTitle>Atomic claims</CardTitle></CardHeader><CardContent className="grid gap-2"><div className="grid gap-2"><input className="min-w-0 rounded-md border px-2 py-1 text-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter claims" aria-label="Filter atomic claims"/><select className="rounded-md border px-2 py-1 text-xs" value={label} onChange={(event) => setLabel(event.target.value)} aria-label="Filter claims by label"><option value="all">All labels</option>{labels.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>{visible.map((claim) => <button key={claim.id} onClick={() => onSelect(claim.id)} className={cn("grid gap-2 rounded-md border bg-white p-3 text-left hover:border-primary", selectedId === claim.id && "border-primary bg-secondary/60", detailed && "p-4")}><div><Badge tone={claim.final_label?.toLowerCase().includes("support") ? "support" : "info"}>{claim.final_label ?? "Not verified"}</Badge><span className="ml-2 text-xs text-muted-foreground">Weight {claim.importance_weight}</span></div><span className="text-sm font-medium">{claim.claim_text}</span><span className="text-xs text-muted-foreground">Support {claim.support_score ?? "-"} - Confidence {claim.confidence_score ?? "-"} - Context {claim.context_completeness ?? "-"}</span>{detailed && [...claim.ambiguities, ...claim.gaps].map((gap) => <span key={gap} className="text-xs text-muted-foreground">{gap}</span>)}</button>)}{visible.length === 0 && <p className="text-xs text-muted-foreground">No claims match these filters.</p>}</CardContent></Card>;
}

function EvidenceColumns({ items, onOpen }: { items: ReportWorkspaceData["report"]["evidence"]; onOpen: (passageId: string, sourceUrl: string) => void }) {
  const supporting = items.filter((item) => item.stance.includes("SUPPORTS"));
  const contradicting = items.filter((item) => item.stance.includes("CONTRADICTS"));
  const neutral = items.filter((item) => !item.stance.includes("SUPPORTS") && !item.stance.includes("CONTRADICTS"));
  return <div className="grid gap-4 lg:grid-cols-2"><EvidenceGroup title="Supporting evidence" items={supporting} onOpen={onOpen}/><EvidenceGroup title="Contradicting evidence" items={contradicting} onOpen={onOpen}/>{neutral.length > 0 && <div className="lg:col-span-2"><EvidenceGroup title="Neutral evidence" items={neutral} onOpen={onOpen}/></div>}</div>;
}

function EvidenceGroup({ title, items, onOpen }: { title: string; items: ReportWorkspaceData["report"]["evidence"]; onOpen: (passageId: string, sourceUrl: string) => void }) {
  return <section className="grid content-start gap-2"><h3 className="text-sm font-semibold">{title}</h3>{items.map((item) => <button key={item.id} onClick={() => onOpen(item.passage_id, item.source_url)} className="grid gap-2 rounded-md border bg-white p-4 text-left hover:border-primary"><div><Badge tone={stanceTone(item.stance)}>{item.stance.replaceAll("_", " ")}</Badge><span className="ml-2 text-xs text-muted-foreground">{item.source_title ?? item.source_url} - {item.page_or_position ?? "stored passage"}</span></div><blockquote className="border-l-4 border-primary pl-3 text-sm leading-6">{item.passage_text}</blockquote><span className="text-xs text-muted-foreground">Adjusted weight {item.adjusted_weight} - Dependency {item.dependency_multiplier} - Citation {item.citation_status}</span></button>)}{items.length === 0 && <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">No evidence in this category.</p>}</section>;
}

function SpecializedPanels({ report }: { report: ReportWorkspaceData["report"] }) {
  const attribution = report.calculations.find((row) => row.formula_name === "attribution_support" && row.atomic_claim_id === null);
  const quote = report.calculations.find((row) => row.formula_name === "quote_fidelity" && row.atomic_claim_id === null);
  const context = report.calculations.find((row) => row.formula_name === "context_completeness" && row.atomic_claim_id === null);
  if (!attribution && !quote && !context) return null;
  return <div className="grid gap-3 md:grid-cols-3">{attribution && <ScorePanel title="Attribution support" record={attribution}/>} {quote && <ScorePanel title="Quote fidelity" record={quote}/>} {context && <ScorePanel title="Surrounding context" record={context}/>}</div>;
}

function ScorePanel({ title, record }: { title: string; record: ReportWorkspaceData["report"]["calculations"][number] }) {
  return <div className="rounded-md border bg-white p-3"><p className="text-xs text-muted-foreground">{title}</p><p className="mt-1 text-2xl font-semibold">{String(record.result.score ?? "Not scored")}</p><p className="mt-1 text-xs text-muted-foreground">Calculation {record.id}</p></div>;
}

function SourceDrawer({ source, passage, mobileOpen, onClose, onPassage }: { source?: SourceRecord; passage?: SourceRecord["passages"][number]; mobileOpen: boolean; onClose: () => void; onPassage: (id: string | null) => void }) {
  if (!source) return <aside className="rounded-lg border bg-white p-4 text-sm text-muted-foreground">No sources were stored for this report.</aside>;
  return <aside className={cn("fixed inset-0 z-50 overflow-y-auto bg-white p-4 xl:static xl:z-auto xl:max-h-[calc(100vh-10rem)] xl:self-start xl:rounded-lg xl:border", !mobileOpen && "hidden xl:block")}><div className="flex items-start justify-between gap-2"><div><p className="font-semibold">{source.title ?? source.domain}</p><p className="text-xs text-muted-foreground">{source.publisher ?? source.author ?? source.domain}</p></div><Button size="icon" variant="ghost" onClick={onClose} aria-label="Close source drawer"><X className="h-4 w-4"/></Button></div><Badge tone={source.access_status === "FETCHED" ? "support" : "warning"}>{source.access_status}</Badge>
    <a className="mt-3 flex items-center gap-1 break-all text-xs text-primary" href={source.canonical_url} target="_blank" rel="noreferrer">Open source <ExternalLink className="h-3 w-3"/></a>
    <dl className="mt-3 grid gap-2 text-xs">{[["Role", source.role], ["Type", source.source_type], ["Published", source.published_at ? new Date(source.published_at).toLocaleString() : "Unavailable"], ["Retrieved", source.retrieved_at ? new Date(source.retrieved_at).toLocaleString() : "Unavailable"], ["Snapshot", source.snapshot_id ? `${source.snapshot_id} v${source.snapshot_version}` : "Unavailable"], ["Parser", source.parser_name ? `${source.parser_name} ${source.parser_version ?? ""}` : "Not parsed"], ["Content hash", source.content_hash ?? "Unavailable"], ["Correction", source.correction_status ?? "None recorded"]].map(([key, value]) => <div key={key} className="grid grid-cols-[90px_1fr] gap-2"><dt className="text-muted-foreground">{key}</dt><dd className="break-all">{value}</dd></div>)}</dl>
    {Object.keys(source.snapshot_metadata).length > 0 && <details className="mt-3 rounded-md border p-2 text-xs"><summary className="cursor-pointer font-semibold">Snapshot metadata</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(source.snapshot_metadata, null, 2)}</pre></details>}
    <p className="mt-3 text-xs">{source.retrieval_reason ?? source.inaccessible_reason ?? source.failure_reason}</p>
    <div className="mt-4 grid gap-2"><p className="text-sm font-semibold">Exact passage - Cited passages</p>{passage ? <><blockquote className="rounded-md border-l-4 border-primary bg-muted/50 p-3 text-sm leading-6">{passage.text}</blockquote><p className="text-xs text-muted-foreground">{passage.heading_path ?? "No heading"} - {passage.page_or_position ?? `paragraph ${passage.paragraph_index ?? "unrecorded"}`} - extraction {Math.round(passage.extraction_certainty * 100)}%</p>{(passage.speaker || passage.table_ref) && <p className="text-xs text-muted-foreground">Speaker: {passage.speaker ?? "not recorded"} - Table: {passage.table_ref ?? "not recorded"}</p>}{Object.keys(passage.metadata).length > 0 && <details className="rounded-md border p-2 text-xs"><summary className="cursor-pointer font-semibold">Passage metadata</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(passage.metadata, null, 2)}</pre></details>}{passage.citations.map((citation) => <div key={citation.id} className="rounded-md border p-2 text-xs"><strong>{citation.report_section}</strong> - {citation.audit_status}<p className="mt-1">{citation.sentence_text}</p>{citation.audit_note && <p className="mt-1 text-muted-foreground">{citation.audit_note}</p>}</div>)}</> : <p className="text-xs text-muted-foreground">No stored passage is available.</p>}
      {source.passages.length > 1 && <select className="rounded-md border p-2 text-xs" value={passage?.id ?? ""} onChange={(event) => onPassage(event.target.value)} aria-label="Select source passage">{source.passages.map((item) => <option key={item.id} value={item.id}>{item.page_or_position ?? item.heading_path ?? item.id}</option>)}</select>}
    </div>
  </aside>;
}

function stanceTone(stance: EvidenceStance) { return stance.includes("SUPPORTS") ? "support" : stance.includes("CONTRADICTS") ? "danger" : "neutral"; }
function Json({ title, value }: { title: string; value: Record<string, unknown> }) { return <div><p className="mb-1 text-xs font-semibold">{title}</p><pre className="overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(value, null, 2)}</pre></div>; }
function Version({ title, value }: { title: string; value: Record<string, unknown> }) { return <div className="rounded-md border p-3"><p className="mb-2 text-sm font-semibold">{title}</p><dl className="grid gap-2 text-xs md:grid-cols-2">{Object.entries(value).map(([key, item]) => <div key={key} className="rounded bg-muted p-2"><dt className="text-muted-foreground">{key}</dt><dd className="mt-1 break-all font-medium">{String(item)}</dd></div>)}</dl></div>; }
