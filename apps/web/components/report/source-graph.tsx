"use client";

import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo, useState } from "react";

import type { ReportRecord, SourceGraphRecord } from "@/lib/report-types";

type Filters = { claim: string; relationship: string; role: string; access: string; cluster: string };
const initialFilters: Filters = { claim: "all", relationship: "all", role: "all", access: "all", cluster: "all" };

export function SourceGraph({ graph, claims, onSourceSelect }: { graph: SourceGraphRecord; claims: ReportRecord["atomic_claims"]; onSourceSelect?: (sourceId: string) => void }) {
  const [filters, setFilters] = useState(initialFilters);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const sourceNodes = useMemo(() => graph.nodes.filter((node) => node.type === "source"), [graph.nodes]);
  const relationships = useMemo(() => [...new Set(graph.edges.map((edge) => edge.relationship))], [graph.edges]);
  const roles = useMemo(() => [...new Set(sourceNodes.flatMap((node) => typeof node.data.role === "string" ? [node.data.role] : []))], [sourceNodes]);
  const accessStates = useMemo(() => [...new Set(sourceNodes.flatMap((node) => typeof node.data.accessStatus === "string" ? [node.data.accessStatus] : []))], [sourceNodes]);
  const clusterNodes = useMemo(() => graph.nodes.filter((node) => node.type === "cluster"), [graph.nodes]);
  const visibleSourceIds = useMemo(() => new Set(sourceNodes.filter((node) => {
    const claimIds = Array.isArray(node.data.atomicClaimIds) ? node.data.atomicClaimIds : [];
    return (filters.claim === "all" || claimIds.includes(filters.claim))
      && (filters.role === "all" || node.data.role === filters.role)
      && (filters.access === "all" || node.data.accessStatus === filters.access)
      && (filters.cluster === "all" || node.data.clusterId === filters.cluster);
  }).map((node) => node.id)), [filters, sourceNodes]);
  const visibleGraphNodes = useMemo(() => graph.nodes.filter((node) => {
    if (node.type === "source") return visibleSourceIds.has(node.id);
    const sourceId = typeof node.data.sourceId === "string" ? `source:${node.data.sourceId}` : null;
    if (sourceId) return visibleSourceIds.has(sourceId);
    if (node.type === "cluster") return sourceNodes.some((source) => visibleSourceIds.has(source.id) && source.data.clusterId === node.data.clusterId);
    return true;
  }), [graph.nodes, sourceNodes, visibleSourceIds]);
  const visibleNodeIds = useMemo(() => new Set(visibleGraphNodes.map((node) => node.id)), [visibleGraphNodes]);
  const nodes = useMemo<Node[]>(() => visibleGraphNodes.map((node) => ({ id: node.id, position: node.position, data: { label: node.label }, style: { borderRadius: 2, borderStyle: node.type === "snapshot" ? "dashed" : "solid", borderColor: node.data.evidenceUsed === true ? "hsl(var(--primary))" : "hsl(var(--border))", borderWidth: node.data.evidenceUsed === true ? 3 : 1, background: node.data.evidenceUsed === true ? "hsl(var(--primary) / 0.08)" : "hsl(var(--card))", color: "hsl(var(--foreground))" } })), [visibleGraphNodes]);
  const edges = useMemo<Edge[]>(() => graph.edges.filter((edge) => filters.relationship === "all" || edge.relationship === filters.relationship).filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)).map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, label: edge.label, animated: edge.relationship === "CITES" })), [filters.relationship, graph.edges, visibleNodeIds]);
  const selectedEdge = graph.edges.find((edge) => edge.id === selectedEdgeId);
  const set = (key: keyof Filters, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  if (graph.nodes.length === 0) return <p className="border border-dashed p-4 text-sm text-muted-foreground">No source dependency graph records were stored.</p>;
  return <div className="grid gap-3">
    <div className="grid gap-2 border bg-muted/40 p-3 sm:grid-cols-2 xl:grid-cols-5">
      <Filter label="atomic claim" value={filters.claim} onChange={(value) => set("claim", value)} options={claims.map((claim) => ({ value: claim.id, label: claim.claim_text }))}/>
      <Filter label="relationship" value={filters.relationship} onChange={(value) => set("relationship", value)} options={relationships.map(option)}/>
      <Filter label="source role" value={filters.role} onChange={(value) => set("role", value)} options={roles.map(option)}/>
      <Filter label="access status" value={filters.access} onChange={(value) => set("access", value)} options={accessStates.map(option)}/>
      <Filter label="cluster" value={filters.cluster} onChange={(value) => set("cluster", value)} options={clusterNodes.map((node) => ({ value: String(node.data.clusterId), label: node.label }))}/>
    </div>
    <p className="flex items-center gap-2 text-xs leading-5 text-muted-foreground"><span className="inline-block h-3 w-3 border-2 border-primary bg-primary/10" aria-hidden="true"/>Outlined nodes contain evidence used in the citation-audited report.</p>
    <div aria-hidden="true" className="h-[430px] overflow-hidden border bg-card"><ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} onEdgeClick={(_, edge) => setSelectedEdgeId(edge.id)} onNodeClick={(_, node) => { const sourceId = graph.nodes.find((item) => item.id === node.id)?.data.sourceId; if (typeof sourceId === "string") onSourceSelect?.(sourceId); }}><MiniMap pannable zoomable/><Controls/><Background color="hsl(var(--border))" gap={20}/></ReactFlow></div>
    <div className="border bg-card p-4 text-sm" aria-label="Accessible source graph summary"><p className="font-editorial text-lg font-semibold">Graph summary</p><p className="mt-1 text-muted-foreground">{nodes.length} visible nodes and {edges.length} visible relationships.</p><ul className="mt-3 grid gap-1 text-foreground">{visibleGraphNodes.filter((node) => typeof node.data.sourceId !== "string").map((node) => <li key={node.id}>{node.type}: {node.label}</li>)}</ul><details className="mt-3 border-t pt-2"><summary className="min-h-11 cursor-pointer py-3 font-medium">Graph links ({visibleGraphNodes.filter((node) => typeof node.data.sourceId === "string").length + edges.length})</summary><ul className="grid gap-1">{visibleGraphNodes.map((node) => { const sourceId = node.data.sourceId; return typeof sourceId === "string" ? <li key={node.id}><button type="button" className="min-h-11 cursor-pointer text-left text-primary underline underline-offset-4" onClick={() => onSourceSelect?.(sourceId)}>{node.type}: {node.label}</button></li> : null; })}{edges.map((edge) => <li key={edge.id}><button type="button" className="min-h-11 cursor-pointer text-left text-primary underline underline-offset-4" onClick={() => setSelectedEdgeId(edge.id)}>{edge.source} → {edge.target}: {String(edge.label ?? "relationship")}</button></li>)}</ul></details></div>
    {selectedEdge && <div className="border border-primary/40 bg-primary/5 p-4 text-sm"><strong>{selectedEdge.relationship.replaceAll("_", " ")}</strong><span className="ml-2 text-muted-foreground">confidence {Math.round(selectedEdge.confidence * 100)}% / {String(selectedEdge.data.detectionMethod ?? "recorded relationship")}</span></div>}
  </div>;
}

function option(value: string) { return { value, label: value.replaceAll("_", " ") }; }
function Filter({ label, value, options, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return <label className="grid gap-1 font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground">{label}<select aria-label={`Filter graph by ${label}`} className="min-h-11 min-w-0 rounded-sm border bg-card px-2 font-sans text-xs normal-case tracking-normal text-foreground" value={value} onChange={(event) => onChange(event.target.value)}><option value="all">All {label}s</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>;
}
