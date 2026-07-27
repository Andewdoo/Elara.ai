"use client";

import { ExternalLink, FileWarning, Info, PanelRightClose, PanelRightOpen, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { ScoreCharts } from "@/components/report/score-charts";
import { ReportHeaderActions } from "@/components/report/report-actions";
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
];

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
  const generated = new Date(report.generated_at).toLocaleString();
  const summarySentences = report.report_sentences.filter((sentence) => sentence.report_section === "summary");
  const factualSentences = report.report_sentences.filter((sentence) => sentence.report_section === "factual_finding");
  const attributionSentences = report.report_sentences.filter((sentence) => sentence.report_section === "attribution");
  const contradictionSentences = report.report_sentences.filter((sentence) => sentence.report_section === "strongest_contradiction");
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!direction && !["Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + direction + tabs.length) % tabs.length;
    openTab(tabs[nextIndex].id);
    document.getElementById(`report-tab-${tabs[nextIndex].id}`)?.focus();
  };

  return <div className="grid gap-4">
    <header className="grid gap-3 rounded-lg border bg-white p-4 shadow-subtle lg:grid-cols-[1fr_auto]">
      <div><div className="flex flex-wrap items-center gap-2"><Badge tone={run.status === "COMPLETED" ? "support" : "info"}>{run.status}</Badge><Badge tone="info">{run.research_depth}</Badge>{isLite && <Badge tone="neutral">Curated Lite library</Badge>}</div><h1 className="mt-3 text-2xl font-semibold">{run.title ?? "Verification report"}</h1><p className="mt-2 text-sm text-muted-foreground">Evidence reviewed as of {reviewed}. Report generated {generated}. New evidence or corrections may change this assessment.</p>{report.workspace_scope && <p className="mt-2 text-xs leading-5 text-muted-foreground">{report.workspace_scope}</p>}</div>
      <div className="grid min-w-60 gap-3"><div className="grid gap-1 rounded-md border bg-muted/40 p-3"><span className="text-xs text-muted-foreground">{isLite ? "Lite result" : "Verdict"}</span><span className="text-lg font-semibold">{report.verdict ?? "Not verified"}</span></div>{run.is_owner && <ReportHeaderActions runId={run.run_id} saved={Boolean(run.saved_at)} />}</div>
    </header>

    <nav role="tablist" className="flex gap-2 overflow-x-auto rounded-lg border bg-white p-2" aria-label="Report sections">
      {tabs.map((tab, index) => <Button role="tab" id={`report-tab-${tab.id}`} aria-selected={activeReportTab === tab.id} aria-controls={`report-panel-${tab.id}`} tabIndex={activeReportTab === tab.id ? 0 : -1} key={tab.id} size="sm" variant={activeReportTab === tab.id ? "primary" : "ghost"} onKeyDown={(event) => onTabKeyDown(event, index)} onClick={() => openTab(tab.id)}>{tab.label}</Button>)}
      <Button className="ml-auto hidden xl:inline-flex" size="icon" variant="ghost" aria-label={ui.sourceDrawerOpen ? "Close source drawer" : "Open source drawer"} onClick={() => ui.setSourceDrawerOpen(!ui.sourceDrawerOpen)}>{ui.sourceDrawerOpen ? <PanelRightClose className="h-4 w-4"/> : <PanelRightOpen className="h-4 w-4"/>}</Button>
    </nav>

    <div className={cn("grid gap-4", ui.sourceDrawerOpen ? "xl:grid-cols-[260px_minmax(0,1fr)_340px]" : "xl:grid-cols-[260px_minmax(0,1fr)]")}>
      <aside className="hidden self-start xl:block"><ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim}/></aside>
      <main role="tabpanel" id={`report-panel-${activeReportTab}`} aria-labelledby={`report-tab-${activeReportTab}`} tabIndex={0} className="min-w-0 grid gap-4">
        {activeReportTab === "overview" && <><Card><CardHeader><CardTitle>Report overview</CardTitle></CardHeader><CardContent className="grid gap-4">
          {report.answer_markdown && <section className="grid gap-2"><h3 className="text-sm font-semibold">Cited answer</h3><div className="rounded-md border bg-muted/40 p-3 text-sm leading-6 whitespace-pre-wrap">{report.answer_markdown}</div></section>}
          <SentenceSection title="Summary" sentences={summarySentences} empty="No citation-audited summary sentences were stored." onOpen={openEvidence}/>
          <SentenceSection title="Factual findings" sentences={factualSentences} empty="No separate factual findings were stored." onOpen={openEvidence}/>
          <SentenceSection title="Attribution findings" sentences={attributionSentences} empty="No attribution finding applies to this report." onOpen={openEvidence}/>
          <SentenceSection title="Strongest credible contradiction" sentences={contradictionSentences} empty="No credible contradiction was identified in the reviewed evidence." onOpen={openEvidence}/>
          <SpecializedPanels report={report}/>
          <div><p className="mb-2 text-sm font-semibold">Limitations</p>{report.limitations.length ? report.limitations.map((item, index) => <p key={`${item}-${index}`} className="mb-2 flex gap-2 rounded-md bg-muted p-3 text-sm"><Info className="mt-0.5 h-4 w-4 shrink-0 text-primary"/>{item}</p>) : <p className="text-sm text-muted-foreground">No limitations were recorded.</p>}</div>
        </CardContent></Card>{!isLite && <ScoreCharts report={report}/>}</>}
        {activeReportTab === "claims" && <ClaimRail claims={report.atomic_claims} selectedId={selectedClaim?.id} onSelect={ui.selectClaim} detailed/>}
        {activeReportTab === "evidence" && <Card><CardHeader><div className="flex items-center justify-between gap-3"><CardTitle>Evidence passages</CardTitle><select className="rounded-md border bg-white px-2 py-1 text-xs" value={ui.evidenceFilter} onChange={(event) => ui.setEvidenceFilter(event.target.value as typeof ui.evidenceFilter)}><option value="all">All</option><option value="supporting">Supporting</option><option value="contradicting">Contradicting</option><option value="inaccessible">Inaccessible</option></select></div></CardHeader><CardContent className="grid gap-3">
          {ui.evidenceFilter === "inaccessible" ? <InaccessibleSources sources={sources} onSelect={ui.selectSource}/> : <EvidenceColumns items={evidence} onOpen={openEvidence} mode={mode}/>}
        </CardContent></Card>}
        {activeReportTab === "graph" && <Card><CardHeader><CardTitle>Source dependency graph</CardTitle></CardHeader><CardContent><SourceGraph graph={sourceGraph} claims={report.atomic_claims} onSourceSelect={ui.selectSource}/></CardContent></Card>}
      </main>
      {ui.sourceDrawerOpen && <SourceDrawer mode={mode} mobileOpen={Boolean(ui.selectedSourceId)} source={selectedSource} passage={selectedPassage} onClose={() => ui.setSourceDrawerOpen(false)} onPassage={ui.selectEvidence}/>}
    </div>
  </div>;
}

function SentenceSection({ title, sentences, empty, onOpen }: { title: string; sentences: ReportWorkspaceData["report"]["report_sentences"]; empty: string; onOpen: (passageId: string, sourceUrl: string) => void }) {
  return <section className="grid gap-2"><h3 className="text-sm font-semibold">{title}</h3>{sentences.map((sentence) => <button key={sentence.id} className="rounded-md border bg-white p-3 text-left text-sm leading-6 hover:border-primary" onClick={() => onOpen(sentence.passage_id, "")}>{sentence.sentence_text}<span className="ml-2 text-xs text-muted-foreground">citation {sentence.audit_status}</span></button>)}{sentences.length === 0 && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">{empty}</p>}</section>;
}

function InaccessibleSources({ sources, onSelect }: { sources: SourceRecord[]; onSelect: (id: string | null) => void }) {
  const inaccessible = sources.filter((source) => source.access_status !== "FETCHED");
  return <>{inaccessible.map((source) => <button key={source.id} onClick={() => onSelect(source.id)} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-left"><FileWarning className="inline h-4 w-4 text-amber-700" aria-hidden="true"/> <strong>{source.title ?? source.domain}</strong><p className="mt-1 text-sm">{source.inaccessible_reason ?? source.failure_reason ?? source.access_status}</p></button>)}{inaccessible.length === 0 && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No inaccessible sources were recorded.</p>}</>;
}

function ClaimRail({ claims, selectedId, onSelect, detailed = false }: { claims: ReportWorkspaceData["report"]["atomic_claims"]; selectedId?: string; onSelect: (id: string | null) => void; detailed?: boolean }) {
  const [query, setQuery] = useState("");
  const [label, setLabel] = useState("all");
  const labels = [...new Set(claims.map((claim) => claim.final_label).filter((value): value is string => Boolean(value)))];
  const visible = claims.filter((claim) => (label === "all" || claim.final_label === label) && claim.claim_text.toLowerCase().includes(query.toLowerCase()));
  return <Card><CardHeader><CardTitle>Atomic claims</CardTitle></CardHeader><CardContent className="grid gap-2"><div className="grid gap-2"><input className="min-w-0 rounded-md border px-2 py-1 text-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter claims" aria-label="Filter atomic claims"/><select className="rounded-md border px-2 py-1 text-xs" value={label} onChange={(event) => setLabel(event.target.value)} aria-label="Filter claims by label"><option value="all">All labels</option>{labels.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>{visible.map((claim) => <button key={claim.id} onClick={() => onSelect(claim.id)} className={cn("grid gap-2 rounded-md border bg-white p-3 text-left hover:border-primary", selectedId === claim.id && "border-primary bg-secondary/60", detailed && "p-4")}><div><Badge tone={claim.final_label?.toLowerCase().includes("support") ? "support" : "info"}>{claim.final_label ?? "Not verified"}</Badge><span className="ml-2 text-xs text-muted-foreground">Weight {claim.importance_weight}</span></div><span className="text-sm font-medium">{claim.claim_text}</span><span className="text-xs text-muted-foreground">Support {claim.support_score ?? "-"} - Confidence {claim.confidence_score ?? "-"} - Context {claim.context_completeness ?? "-"}</span>{detailed && [...claim.ambiguities, ...claim.gaps].map((gap) => <span key={gap} className="text-xs text-muted-foreground">{gap}</span>)}</button>)}{visible.length === 0 && <p className="text-xs text-muted-foreground">No claims match these filters.</p>}</CardContent></Card>;
}

function EvidenceColumns({ items, onOpen, mode }: { items: ReportWorkspaceData["report"]["evidence"]; onOpen: (passageId: string, sourceUrl: string) => void; mode: ReportWorkspaceData["mode"] }) {
  const supporting = items.filter((item) => item.stance.includes("SUPPORTS"));
  const contradicting = items.filter((item) => item.stance.includes("CONTRADICTS"));
  const neutral = items.filter((item) => !item.stance.includes("SUPPORTS") && !item.stance.includes("CONTRADICTS"));
  return <div className="grid gap-4 lg:grid-cols-2"><EvidenceGroup title="Supporting evidence" items={supporting} onOpen={onOpen} mode={mode}/><EvidenceGroup title="Contradicting evidence" items={contradicting} onOpen={onOpen} mode={mode}/>{neutral.length > 0 && <div className="lg:col-span-2"><EvidenceGroup title="Neutral evidence" items={neutral} onOpen={onOpen} mode={mode}/></div>}</div>;
}

function EvidenceGroup({ title, items, onOpen, mode }: { title: string; items: ReportWorkspaceData["report"]["evidence"]; onOpen: (passageId: string, sourceUrl: string) => void; mode: ReportWorkspaceData["mode"] }) {
  const isLite = mode === "lite";
  return <section className="grid content-start gap-2"><h3 className="text-sm font-semibold">{title}</h3>{items.map((item) => <button key={item.id} onClick={() => onOpen(item.passage_id, item.source_url)} className="grid gap-2 rounded-md border bg-white p-4 text-left hover:border-primary"><div><Badge tone={stanceTone(item.stance)}>{item.stance.replaceAll("_", " ")}</Badge><span className="ml-2 text-xs text-muted-foreground">{item.source_title ?? item.source_url} - {item.page_or_position ?? (isLite ? "stored Lite chunk" : "stored passage")}</span></div><blockquote className="border-l-4 border-primary pl-3 text-sm leading-6">{item.passage_text}</blockquote><span className="text-xs text-muted-foreground">{isLite ? `Citation ${item.citation_status} - Lite evidence confidence ${item.adjusted_weight}%` : `Adjusted weight ${item.adjusted_weight} - Dependency ${item.dependency_multiplier} - Citation ${item.citation_status}`}</span></button>)}{items.length === 0 && <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">No evidence in this category.</p>}</section>;
}

function SpecializedPanels({ report }: { report: ReportWorkspaceData["report"] }) {
  const attribution = report.calculations.find((row) => row.formula_name === "attribution_support" && row.atomic_claim_id === null);
  const quote = report.calculations.find((row) => row.formula_name === "quote_fidelity" && row.atomic_claim_id === null);
  const context = report.calculations.find((row) => row.formula_name === "context_completeness" && row.atomic_claim_id === null);
  if (!attribution && !quote && !context) return null;
  return <div className="grid gap-3 md:grid-cols-3">{attribution && <ScorePanel title="Attribution support" record={attribution}/>} {quote && <ScorePanel title="Quote fidelity" record={quote}/>} {context && <ScorePanel title="Surrounding context" record={context}/>}</div>;
}

function ScorePanel({ title, record }: { title: string; record: ReportWorkspaceData["report"]["calculations"][number] }) {
  return <div className="rounded-md border bg-white p-3"><p className="text-xs text-muted-foreground">{title}</p><p className="mt-1 text-2xl font-semibold">{String(record.result.score ?? "Not scored")}</p></div>;
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
      const first = items[0]; const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    drawer.addEventListener("keydown", onKeyDown);
    return () => { drawer.removeEventListener("keydown", onKeyDown); previousFocusRef.current?.focus(); };
  }, [mobileOpen, onClose]);
  const isLite = mode === "lite";
  if (!source) return <aside className="rounded-lg border bg-white p-4 text-sm text-muted-foreground">No sources were stored for this report.</aside>;
  return <aside ref={drawerRef} role="dialog" aria-modal={mobileOpen} aria-labelledby="source-drawer-title" className={cn("fixed inset-0 z-50 overflow-y-auto bg-white p-4 xl:static xl:z-auto xl:max-h-[calc(100vh-10rem)] xl:self-start xl:rounded-lg xl:border", !mobileOpen && "hidden xl:block")}><div className="flex items-start justify-between gap-2"><div><p id="source-drawer-title" className="font-semibold">{source.title ?? source.domain}</p><p className="text-xs text-muted-foreground">{source.publisher ?? source.author ?? source.domain}</p></div><Button size="icon" variant="ghost" onClick={onClose} aria-label="Close source drawer"><X className="h-4 w-4" aria-hidden="true"/></Button></div><Badge tone={source.access_status === "FETCHED" ? "support" : "warning"}>{source.access_status}</Badge>
    {source.canonical_url ? <a className="mt-3 flex items-center gap-1 break-all text-xs text-primary" href={source.canonical_url} target="_blank" rel="noreferrer">Open source <ExternalLink className="h-3 w-3"/></a> : <p className="mt-3 text-xs text-muted-foreground">Stored curated Lite source metadata only; no public source URL was provided.</p>}
    <dl className="mt-3 grid gap-2 text-xs">{[["Role", source.role], ["Type", source.source_type], ["Published", source.published_at ? new Date(source.published_at).toLocaleString() : "Unavailable"], ["Retrieved", source.retrieved_at ? new Date(source.retrieved_at).toLocaleString() : "Unavailable"], ["Correction", source.correction_status ?? "None recorded"]].map(([key, value]) => <div key={key} className="grid grid-cols-[90px_1fr] gap-2"><dt className="text-muted-foreground">{key}</dt><dd className="break-all">{value}</dd></div>)}</dl>
    <div className="mt-3 text-xs"><p className="font-semibold">Correction history</p>{source.correction_history.length ? source.correction_history.map((item) => <p key={item.snapshot_id} className="mt-1 rounded border p-2">Snapshot v{item.snapshot_version}: {item.status} · {new Date(item.retrieved_at).toLocaleString()}</p>) : <p className="mt-1 text-muted-foreground">No correction notices were recorded.</p>}</div>
    <div className="mt-4 grid gap-2"><p className="text-sm font-semibold">{isLite ? "Exact source chunk - Cited sentences" : "Exact passage - Cited passages"}</p>{passage ? <><blockquote className="rounded-md border-l-4 border-primary bg-muted/50 p-3 text-sm leading-6">{passage.text}</blockquote><p className="text-xs text-muted-foreground">{passage.heading_path ?? "No heading"} - {passage.page_or_position ?? `paragraph ${passage.paragraph_index ?? "unrecorded"}`} - {isLite ? "retrieval confidence" : "extraction"} {Math.round(passage.extraction_certainty * 100)}%</p>{(passage.speaker || passage.table_ref) && <p className="text-xs text-muted-foreground">Speaker: {passage.speaker ?? "not recorded"} - Table: {passage.table_ref ?? "not recorded"}</p>}{passage.citations.map((citation) => <div key={citation.id} className="rounded-md border p-2 text-xs"><strong>{citation.report_section}</strong> - {citation.audit_status}<p className="mt-1">{citation.sentence_text}</p>{citation.audit_note && <p className="mt-1 text-muted-foreground">{citation.audit_note}</p>}</div>)}</> : <p className="text-xs text-muted-foreground">No stored passage is available.</p>}
      {source.passages.length > 1 && <select className="rounded-md border p-2 text-xs" value={passage?.id ?? ""} onChange={(event) => onPassage(event.target.value)} aria-label="Select source passage">{source.passages.map((item) => <option key={item.id} value={item.id}>{item.page_or_position ?? item.heading_path ?? item.id}</option>)}</select>}
    </div>
  </aside>;
}

function stanceTone(stance: EvidenceStance) { return stance.includes("SUPPORTS") ? "support" : stance.includes("CONTRADICTS") ? "danger" : "neutral"; }
