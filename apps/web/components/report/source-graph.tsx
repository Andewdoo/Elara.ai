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
  const nodes = useMemo<Node[]>(() => visibleGraphNodes.map((node) => ({ id: node.id, position: node.position, data: { label: node.label }, style: { borderStyle: node.type === "snapshot" ? "dashed" : "solid", borderColor: node.data.evidenceUsed === true ? "#0f766e" : undefined, borderWidth: node.data.evidenceUsed === true ? 3 : 1, background: node.data.evidenceUsed === true ? "#ecfdf5" : "#fff" } })), [visibleGraphNodes]);
  const edges = useMemo<Edge[]>(() => graph.edges.filter((edge) => filters.relationship === "all" || edge.relationship === filters.relationship).filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)).map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, label: edge.label, animated: edge.relationship === "CITES" })), [filters.relationship, graph.edges, visibleNodeIds]);
  const selectedEdge = graph.edges.find((edge) => edge.id === selectedEdgeId);
  const set = (key: keyof Filters, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  return <div className="grid gap-3">
    <div className="grid gap-2 rounded-lg border bg-white p-2 sm:grid-cols-2 xl:grid-cols-5">
      <Filter label="atomic claim" value={filters.claim} onChange={(value) => set("claim", value)} options={claims.map((claim) => ({ value: claim.id, label: claim.claim_text }))}/>
      <Filter label="relationship" value={filters.relationship} onChange={(value) => set("relationship", value)} options={relationships.map(option)}/>
      <Filter label="source role" value={filters.role} onChange={(value) => set("role", value)} options={roles.map(option)}/>
      <Filter label="access status" value={filters.access} onChange={(value) => set("access", value)} options={accessStates.map(option)}/>
      <Filter label="cluster" value={filters.cluster} onChange={(value) => set("cluster", value)} options={clusterNodes.map((node) => ({ value: String(node.data.clusterId), label: node.label }))}/>
    </div>
    <p className="text-xs text-muted-foreground"><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-700"/>Green nodes contain evidence used in the citation-audited report.</p>
    <div className="h-[430px] overflow-hidden rounded-lg border bg-white"><ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} onEdgeClick={(_, edge) => setSelectedEdgeId(edge.id)} onNodeClick={(_, node) => { const sourceId = graph.nodes.find((item) => item.id === node.id)?.data.sourceId; if (typeof sourceId === "string") onSourceSelect?.(sourceId); }}><MiniMap pannable zoomable/><Controls/><Background/></ReactFlow></div>
    {selectedEdge && <div className="rounded-lg border bg-white p-3 text-sm"><strong>{selectedEdge.relationship.replaceAll("_", " ")}</strong><span className="ml-2 text-muted-foreground">confidence {Math.round(selectedEdge.confidence * 100)}% - {String(selectedEdge.data.detectionMethod ?? "recorded relationship")}</span></div>}
  </div>;
}

function option(value: string) { return { value, label: value.replaceAll("_", " ") }; }
function Filter({ label, value, options, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return <select aria-label={`Filter graph by ${label}`} className="min-w-0 rounded-md border bg-white px-2 py-1 text-xs" value={value} onChange={(event) => onChange(event.target.value)}><option value="all">All {label}s</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>;
}
