"use client";

import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  Camera,
  CheckCircle2,
  Database,
  ExternalLink,
  FileText,
  Focus,
  Maximize2,
  Minimize2,
  Network,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ReportRecord, SourceGraphRecord } from "@/lib/report-types";
import { cn } from "@/lib/utils";

type Filters = { claim: string; relationship: string; role: string; access: string; cluster: string };
type GraphNodeData = {
  label: string;
  nodeType: string;
  meta: string;
  badge: string;
  evidenceUsed: boolean;
  selected: boolean;
  dimmed: boolean;
};
type GraphNode = Node<GraphNodeData, "sourceGraphNode">;

const initialFilters: Filters = { claim: "all", relationship: "all", role: "all", access: "all", cluster: "all" };
const nodeTypes = { sourceGraphNode: SourceGraphNode };

export function SourceGraph({ graph, claims, onSourceSelect }: { graph: SourceGraphRecord; claims: ReportRecord["atomic_claims"]; onSourceSelect?: (sourceId: string) => void }) {
  const [filters, setFilters] = useState(initialFilters);
  const [query, setQuery] = useState("");
  const [usedOnly, setUsedOnly] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [flow, setFlow] = useState<ReactFlowInstance<GraphNode, Edge> | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    if (!isFullscreen) return;
    const previousOverflow = document.body.style.overflow;
    const exitOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setIsFullscreen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", exitOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", exitOnEscape);
    };
  }, [isFullscreen]);

  const allNodeIds = useMemo(() => new Set(graph.nodes.map((node) => node.id)), [graph.nodes]);
  const sourceNodes = useMemo(() => graph.nodes.filter((node) => node.type === "source"), [graph.nodes]);
  const relationships = useMemo(() => [...new Set(graph.edges.map((edge) => edge.relationship))], [graph.edges]);
  const roles = useMemo(() => [...new Set(sourceNodes.flatMap((node) => typeof node.data.role === "string" ? [node.data.role] : []))], [sourceNodes]);
  const accessStates = useMemo(() => [...new Set(sourceNodes.flatMap((node) => typeof node.data.accessStatus === "string" ? [node.data.accessStatus] : []))], [sourceNodes]);
  const clusterNodes = useMemo(() => graph.nodes.filter((node) => node.type === "cluster"), [graph.nodes]);
  const normalizedQuery = query.trim().toLowerCase();

  const visibleSourceIds = useMemo(() => new Set(sourceNodes.filter((node) => {
    const claimIds = Array.isArray(node.data.atomicClaimIds) ? node.data.atomicClaimIds : [];
    const searchable = [node.label, node.data.role, node.data.accessStatus, node.data.contentType].filter(Boolean).join(" ").toLowerCase();
    return (filters.claim === "all" || claimIds.includes(filters.claim))
      && (filters.role === "all" || node.data.role === filters.role)
      && (filters.access === "all" || node.data.accessStatus === filters.access)
      && (filters.cluster === "all" || node.data.clusterId === filters.cluster)
      && (!normalizedQuery || searchable.includes(normalizedQuery))
      && (!usedOnly || node.data.evidenceUsed === true);
  }).map((node) => node.id)), [filters, normalizedQuery, sourceNodes, usedOnly]);

  const visibleGraphNodes = useMemo(() => graph.nodes.filter((node) => {
    if (node.type === "source") return visibleSourceIds.has(node.id);
    const sourceNodeId = getSourceNodeId(node, allNodeIds);
    if (sourceNodeId) return visibleSourceIds.has(sourceNodeId);
    if (node.type === "cluster") return sourceNodes.some((source) => visibleSourceIds.has(source.id) && source.data.clusterId === node.data.clusterId);
    if (node.type === "atomic_claim" && filters.claim !== "all") return node.data.atomicClaimId === filters.claim;
    return true;
  }), [allNodeIds, filters.claim, graph.nodes, sourceNodes, visibleSourceIds]);
  const visibleNodeIds = useMemo(() => new Set(visibleGraphNodes.map((node) => node.id)), [visibleGraphNodes]);
  const visibleEdges = useMemo(() => graph.edges
    .filter((edge) => filters.relationship === "all" || edge.relationship === filters.relationship)
    .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)), [filters.relationship, graph.edges, visibleNodeIds]);

  const selectedEdge = graph.edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const highlightedEdgeIds = useMemo(() => new Set(visibleEdges.filter((edge) => {
    if (selectedEdgeId) return edge.id === selectedEdgeId;
    return selectedNodeId ? edge.source === selectedNodeId || edge.target === selectedNodeId : false;
  }).map((edge) => edge.id)), [selectedEdgeId, selectedNodeId, visibleEdges]);
  const highlightedNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (selectedNodeId) ids.add(selectedNodeId);
    for (const edge of visibleEdges) {
      if (highlightedEdgeIds.has(edge.id)) { ids.add(edge.source); ids.add(edge.target); }
    }
    return ids;
  }, [highlightedEdgeIds, selectedNodeId, visibleEdges]);
  const hasSelection = Boolean(selectedNodeId || selectedEdgeId);
  const fitViewOptions = useMemo(() => ({
    padding: isFullscreen ? 0.06 : 0.1,
    minZoom: isFullscreen ? 0.68 : 0.48,
    maxZoom: isFullscreen ? 0.9 : 0.82,
  }), [isFullscreen]);

  const nodes = useMemo<GraphNode[]>(() => layoutGraphNodes(visibleGraphNodes, visibleEdges).map((node) => ({
    id: node.id,
    type: "sourceGraphNode",
    position: node.position,
    data: {
      label: node.label,
      nodeType: node.type,
      meta: nodeMeta(node),
      badge: nodeBadge(node),
      evidenceUsed: node.data.evidenceUsed === true,
      selected: highlightedNodeIds.has(node.id),
      dimmed: hasSelection && !highlightedNodeIds.has(node.id),
    },
    focusable: true,
    ariaLabel: `${node.type}: ${node.label}`,
    style: { background: "transparent", border: "none", boxShadow: "none", width: "auto" },
  })), [hasSelection, highlightedNodeIds, visibleEdges, visibleGraphNodes]);

  const edges = useMemo<Edge[]>(() => visibleEdges.map((edge) => {
    const highlighted = highlightedEdgeIds.has(edge.id);
    const dimmed = hasSelection && !highlighted;
    const stroke = highlighted ? "hsl(var(--primary))" : "hsl(var(--muted-foreground))";
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      type: "smoothstep",
      animated: edge.relationship === "CITES" && highlighted,
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
      style: { stroke, strokeWidth: highlighted ? 2.5 : 1.35, opacity: dimmed ? 0.2 : highlighted ? 1 : 0.55 },
      labelStyle: { fill: "hsl(var(--foreground))", fontSize: 10, fontWeight: 600, opacity: dimmed ? 0.2 : 1 },
      labelBgStyle: { fill: "hsl(var(--card))", fillOpacity: 0.96 },
      labelBgPadding: [6, 4],
      labelBgBorderRadius: 4,
    };
  }), [hasSelection, highlightedEdgeIds, visibleEdges]);

  useEffect(() => {
    if (!flow) return;
    const frame = window.requestAnimationFrame(() => {
      void flow.fitView({ ...fitViewOptions, duration: 250 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [fitViewOptions, flow, nodes.length]);

  const selectedConnectionCount = selectedNode ? graph.edges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id).length : 0;
  const selectedSourceId = selectedNode && typeof selectedNode.data.sourceId === "string" ? selectedNode.data.sourceId : null;
  const set = (key: keyof Filters, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  const clearSelection = () => { setSelectedNodeId(null); setSelectedEdgeId(null); };
  const resetFilters = () => { setFilters(initialFilters); setQuery(""); setUsedOnly(false); };

  if (graph.nodes.length === 0) return <p className="border border-dashed p-4 text-sm text-muted-foreground">No source dependency graph records were stored.</p>;

  return <div role={isFullscreen ? "dialog" : undefined} aria-modal={isFullscreen || undefined} aria-label={isFullscreen ? "Fullscreen source dependency graph" : undefined} className={cn("grid gap-3 bg-background", isFullscreen && "fixed inset-0 z-50 h-dvh overflow-y-auto p-4 sm:p-6")}>
    <div className="flex flex-col justify-between gap-3 border-b pb-4 lg:flex-row lg:items-end">
      <div>
        <p className="text-sm leading-6 text-muted-foreground">Trace sources, snapshots, and relationships used in this report.</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[0.64rem] uppercase tracking-wide text-muted-foreground" aria-label="Graph legend">
          <LegendSwatch className="border-primary bg-primary/10" label="Cluster" />
          <LegendSwatch className="border-border bg-card" label="Source" />
          <LegendSwatch className="border-dashed border-muted-foreground bg-muted/40" label="Snapshot" />
          <span className="inline-flex items-center gap-2"><span className="h-0.5 w-5 bg-primary" aria-hidden="true" />Selected path</span>
        </div>
      </div>
      <p className="font-mono text-[0.64rem] uppercase tracking-wide text-muted-foreground">{nodes.length} nodes / {edges.length} relationships</p>
    </div>

    <div className="grid gap-2 border bg-muted/35 p-3 lg:grid-cols-[minmax(220px,1.2fr)_repeat(2,minmax(150px,0.8fr))_repeat(3,auto)]">
      <label className="relative min-w-0">
        <span className="sr-only">Find a source in the graph</span>
        <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <input className="min-h-11 w-full rounded-sm border bg-card pl-9 pr-3 text-sm outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-ring/30" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a source..." aria-label="Find a source in the graph" />
      </label>
      <Filter label="atomic claim" value={filters.claim} onChange={(value) => set("claim", value)} options={claims.map((claim) => ({ value: claim.id, label: claim.claim_text }))}/>
      <Filter label="relationship" value={filters.relationship} onChange={(value) => set("relationship", value)} options={relationships.map(option)}/>
      <button type="button" aria-pressed={usedOnly} className={cn("min-h-11 cursor-pointer rounded-sm border bg-card px-3 text-sm font-medium outline-none transition-colors hover:border-primary focus-visible:ring-2 focus-visible:ring-ring", usedOnly && "border-primary bg-primary/10 text-primary")} onClick={() => setUsedOnly((current) => !current)}><CheckCircle2 className="mr-2 inline h-4 w-4" aria-hidden="true" />Used in report</button>
      <button type="button" className="min-h-11 cursor-pointer rounded-sm border bg-card px-3 text-sm font-medium outline-none transition-colors hover:border-primary focus-visible:ring-2 focus-visible:ring-ring" onClick={() => void flow?.fitView({ ...fitViewOptions, duration: 250 })}><Focus className="mr-2 inline h-4 w-4" aria-hidden="true" />Fit view</button>
      <button type="button" aria-pressed={isFullscreen} className="min-h-11 cursor-pointer rounded-sm border bg-card px-3 text-sm font-medium outline-none transition-colors hover:border-primary focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setIsFullscreen((current) => !current)}>{isFullscreen ? <Minimize2 className="mr-2 inline h-4 w-4" aria-hidden="true" /> : <Maximize2 className="mr-2 inline h-4 w-4" aria-hidden="true" />}{isFullscreen ? "Exit full screen" : "Full screen"}</button>
    </div>

    <div className="grid gap-2 border-x border-b bg-muted/20 p-3 sm:grid-cols-2 xl:grid-cols-4">
      <Filter label="source role" value={filters.role} onChange={(value) => set("role", value)} options={roles.map(option)}/>
      <Filter label="access status" value={filters.access} onChange={(value) => set("access", value)} options={accessStates.map(option)}/>
      <Filter label="cluster" value={filters.cluster} onChange={(value) => set("cluster", value)} options={clusterNodes.map((node) => ({ value: String(node.data.clusterId), label: node.label }))}/>
      <button type="button" className="min-h-11 self-end cursor-pointer rounded-sm border bg-card px-3 text-sm font-medium outline-none transition-colors hover:border-primary focus-visible:ring-2 focus-visible:ring-ring" onClick={resetFilters}><SlidersHorizontal className="mr-2 inline h-4 w-4" aria-hidden="true" />Reset filters</button>
    </div>

    <p className="flex items-center gap-2 text-xs leading-5 text-muted-foreground"><span className="inline-block h-3 w-3 border-2 border-primary bg-primary/10" aria-hidden="true"/>Outlined nodes contain evidence used in the citation-audited report. Drag vertically to explore; select a node or relationship to highlight its path.</p>

    <div className="grid overflow-hidden border bg-card xl:grid-cols-[minmax(0,1fr)_260px]">
      <div aria-hidden="true" className={cn("relative min-w-0 overflow-hidden", isFullscreen ? "h-[calc(100dvh-15rem)] min-h-[720px]" : "h-[640px] lg:h-[760px]")}>
        <div className="pointer-events-none absolute left-1/2 top-3 z-10 hidden w-[calc(100%-3rem)] max-w-3xl -translate-x-1/2 grid-cols-3 font-mono text-[0.62rem] uppercase tracking-[0.1em] text-primary md:grid">
          <span>Topic cluster</span><span className="text-center">Sources</span><span className="text-right">Snapshots</span>
        </div>
        <ReactFlow<GraphNode, Edge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={fitViewOptions}
          minZoom={0.35}
          maxZoom={1.4}
          nodesDraggable={false}
          nodesConnectable={false}
          panOnDrag
          onlyRenderVisibleElements
          onInit={setFlow}
          onPaneClick={clearSelection}
          onEdgeClick={(_, edge) => { setSelectedEdgeId(edge.id); setSelectedNodeId(null); }}
          onNodeClick={(_, node) => {
            setSelectedNodeId(node.id);
            setSelectedEdgeId(null);
            const sourceId = graph.nodes.find((item) => item.id === node.id)?.data.sourceId;
            if (typeof sourceId === "string") onSourceSelect?.(sourceId);
          }}
        >
          <Background variant={BackgroundVariant.Dots} color="hsl(var(--border))" gap={20} size={1}/>
        </ReactFlow>
      </div>

      <aside className="border-t bg-card p-4 xl:border-l xl:border-t-0" aria-live="polite">
        <div className="flex min-h-11 items-start justify-between gap-3 border-b pb-3">
          <div><p className="font-mono text-[0.62rem] uppercase tracking-[0.1em] text-primary">{selectedEdge ? "Selected relationship" : "Selected node"}</p><h3 className="mt-1 font-editorial text-lg font-semibold leading-6">{selectedEdge ? selectedEdge.relationship.replaceAll("_", " ") : selectedNode?.label ?? "Nothing selected"}</h3></div>
          {hasSelection && <button type="button" className="min-h-11 min-w-11 cursor-pointer rounded-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring" onClick={clearSelection} aria-label="Clear graph selection"><X className="mx-auto h-4 w-4" aria-hidden="true" /></button>}
        </div>
        {selectedNode ? <div className="grid gap-4 pt-4 text-sm">
          <div className="flex flex-wrap gap-2"><span className="border bg-muted px-2 py-1 font-mono text-[0.62rem] uppercase">{selectedNode.type.replaceAll("_", " ")}</span>{typeof selectedNode.data.role === "string" && <span className="border border-primary/30 bg-primary/10 px-2 py-1 font-mono text-[0.62rem] uppercase text-primary">{selectedNode.data.role.replaceAll("_", " ")}</span>}</div>
          {selectedNode.data.evidenceUsed === true && <p className="flex items-center gap-2 text-primary"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />Used in report</p>}
          <dl className="grid gap-2 border-y py-3 text-xs"><InspectorRow label="Connections" value={String(selectedConnectionCount)} /><InspectorRow label="Access" value={typeof selectedNode.data.accessStatus === "string" ? selectedNode.data.accessStatus : "Not recorded"} /><InspectorRow label="Content" value={typeof selectedNode.data.contentType === "string" ? selectedNode.data.contentType : "Not recorded"} /></dl>
          {selectedSourceId && <button type="button" className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-sm bg-primary px-3 font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onSourceSelect?.(selectedSourceId)}>Open source <ExternalLink className="h-4 w-4" aria-hidden="true" /></button>}
        </div> : selectedEdge ? <div className="grid gap-4 pt-4 text-sm">
          <p className="leading-6 text-muted-foreground">{nodeLabel(graph.nodes, selectedEdge.source)} <span aria-hidden="true">→</span> {nodeLabel(graph.nodes, selectedEdge.target)}</p>
          <dl className="grid gap-2 border-y py-3 text-xs"><InspectorRow label="Confidence" value={`${Math.round(selectedEdge.confidence * 100)}%`} /><InspectorRow label="Detection" value={String(selectedEdge.data.detectionMethod ?? "Recorded relationship")} /></dl>
        </div> : <p className="pt-4 text-sm leading-6 text-muted-foreground">Select a node to highlight its connected path, or select a relationship to inspect its confidence and detection method.</p>}
      </aside>
    </div>

    <div className="border bg-card p-4 text-sm" aria-label="Accessible source graph summary"><p className="font-editorial text-lg font-semibold">Graph summary</p><p className="mt-1 text-muted-foreground">{nodes.length} visible nodes and {edges.length} visible relationships.</p><ul className="mt-3 grid gap-1 text-foreground">{visibleGraphNodes.filter((node) => typeof node.data.sourceId !== "string").map((node) => <li key={node.id}>{node.type}: {node.label}</li>)}</ul><details className="mt-3 border-t pt-2"><summary className="min-h-11 cursor-pointer py-3 font-medium">Graph links ({visibleGraphNodes.filter((node) => typeof node.data.sourceId === "string").length + edges.length})</summary><ul className="grid gap-1">{visibleGraphNodes.map((node) => { const sourceId = node.data.sourceId; return typeof sourceId === "string" ? <li key={node.id}><button type="button" className="min-h-11 cursor-pointer text-left text-primary underline underline-offset-4" onClick={() => { setSelectedNodeId(node.id); setSelectedEdgeId(null); onSourceSelect?.(sourceId); }}>{node.type}: {node.label}</button></li> : null; })}{edges.map((edge) => <li key={edge.id}><button type="button" className="min-h-11 cursor-pointer text-left text-primary underline underline-offset-4" onClick={() => { setSelectedEdgeId(edge.id); setSelectedNodeId(null); }}>{edge.source} → {edge.target}: {String(edge.label ?? "relationship")}</button></li>)}</ul></details></div>
    {selectedEdge && <div className="border border-primary/40 bg-primary/5 p-4 text-sm"><strong>{selectedEdge.relationship.replaceAll("_", " ")}</strong><span className="ml-2 text-muted-foreground">confidence {Math.round(selectedEdge.confidence * 100)}% / {String(selectedEdge.data.detectionMethod ?? "recorded relationship")}</span></div>}
  </div>;
}

function SourceGraphNode({ data }: NodeProps<GraphNode>) {
  const isCluster = data.nodeType === "cluster" || data.nodeType === "atomic_claim";
  const isSnapshot = data.nodeType === "snapshot";
  const Icon = isCluster ? Network : isSnapshot ? Camera : data.badge.toLowerCase().includes("data") ? Database : FileText;
  return <div className={cn("relative w-[250px] rounded-md border bg-card p-3 text-left shadow-sm transition-opacity", isCluster && "w-[220px] border-primary bg-primary/5", isSnapshot && "w-[190px] border-dashed border-muted-foreground bg-muted/30", data.evidenceUsed && "border-2 border-primary", data.selected && "ring-2 ring-primary/25", data.dimmed && "opacity-30")}>
    <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-2 !border-card !bg-muted-foreground" />
    <div className="flex min-w-0 items-start gap-3"><span className={cn("inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-sm border bg-muted text-foreground", (isCluster || data.selected) && "border-primary/30 bg-primary/10 text-primary")}><Icon className="h-4 w-4" aria-hidden="true" /></span><div className="min-w-0 flex-1"><p className="line-clamp-2 text-sm font-semibold leading-5">{data.label}</p><p className="mt-1 truncate text-[0.68rem] leading-4 text-muted-foreground">{data.meta}</p></div></div>
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2"><span className="rounded-sm border bg-muted/50 px-1.5 py-0.5 font-mono text-[0.56rem] uppercase tracking-wide text-muted-foreground">{data.badge}</span>{data.evidenceUsed && <span className="font-mono text-[0.54rem] uppercase tracking-wide text-primary">Used in report</span>}</div>
    <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-2 !border-card !bg-muted-foreground" />
  </div>;
}

function layoutGraphNodes(nodes: SourceGraphRecord["nodes"], edges: SourceGraphRecord["edges"]): SourceGraphRecord["nodes"] {
  const sorted = [...nodes].sort((a, b) => a.position.y - b.position.y || a.label.localeCompare(b.label));
  const sources = sorted.filter((node) => node.type === "source");
  const snapshots = sorted.filter((node) => node.type === "snapshot");
  const left = sorted.filter((node) => node.type === "cluster" || node.type === "atomic_claim");
  const other = sorted.filter((node) => !["source", "snapshot", "cluster", "atomic_claim"].includes(node.type));
  const sourceY = new Map<string, number>();
  sources.forEach((node, index) => sourceY.set(node.id, 80 + index * 144));
  other.forEach((node, index) => sourceY.set(node.id, 80 + (sources.length + index) * 144));
  const leftY = new Map<string, number>();
  let previousLeftY = -80;
  left.forEach((node, index) => {
    const connected = edges.filter((edge) => edge.source === node.id || edge.target === node.id).map((edge) => sourceY.get(edge.source === node.id ? edge.target : edge.source)).filter((value): value is number => value !== undefined);
    const preferredY = connected.length ? connected.reduce((sum, value) => sum + value, 0) / connected.length : 80 + index * 176;
    const y = Math.max(preferredY, previousLeftY + 176);
    leftY.set(node.id, y);
    previousLeftY = y;
  });
  const snapshotY = new Map<string, number>();
  snapshots.forEach((node, index) => snapshotY.set(node.id, 80 + index * 122));
  return sorted.map((node) => ({
    ...node,
    position: node.type === "cluster" || node.type === "atomic_claim"
      ? { x: 0, y: leftY.get(node.id) ?? 80 }
      : node.type === "snapshot"
        ? { x: 610, y: snapshotY.get(node.id) ?? 80 }
        : { x: 280, y: sourceY.get(node.id) ?? 80 },
  }));
}

function getSourceNodeId(node: SourceGraphRecord["nodes"][number], allNodeIds: Set<string>) {
  const raw = typeof node.data.sourceId === "string" ? node.data.sourceId : null;
  if (!raw) return null;
  if (allNodeIds.has(raw)) return raw;
  const prefixed = `source:${raw}`;
  return allNodeIds.has(prefixed) ? prefixed : null;
}

function nodeMeta(node: SourceGraphRecord["nodes"][number]) {
  if (node.type === "cluster") return `${String(node.data.originType ?? "information cluster").replaceAll("_", " ")}`;
  if (node.type === "snapshot") return String(node.data.accessStatus ?? "stored snapshot").replaceAll("_", " ");
  return [node.data.role, node.data.contentType, node.data.accessStatus].filter((value): value is string => typeof value === "string" && Boolean(value)).map((value) => value.replaceAll("_", " ")).join(" · ") || "Source record";
}

function nodeBadge(node: SourceGraphRecord["nodes"][number]) {
  if (node.type === "cluster") return "Cluster";
  if (node.type === "snapshot") return "Snapshot";
  if (node.type === "atomic_claim") return "Claim";
  return typeof node.data.contentType === "string" ? node.data.contentType : typeof node.data.role === "string" ? node.data.role : node.type;
}

function nodeLabel(nodes: SourceGraphRecord["nodes"], id: string) { return nodes.find((node) => node.id === id)?.label ?? id; }
function InspectorRow({ label, value }: { label: string; value: string }) { return <div className="grid grid-cols-[78px_minmax(0,1fr)] gap-3"><dt className="font-mono text-muted-foreground">{label}</dt><dd className="break-words text-foreground">{value}</dd></div>; }
function LegendSwatch({ className, label }: { className: string; label: string }) { return <span className="inline-flex items-center gap-2"><span className={cn("h-4 w-4 rounded-sm border", className)} aria-hidden="true" />{label}</span>; }
function option(value: string) { return { value, label: value.replaceAll("_", " ") }; }
function Filter({ label, value, options, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return <label className="grid gap-1 font-mono text-[0.62rem] uppercase tracking-wide text-muted-foreground">{label}<select aria-label={`Filter graph by ${label}`} className="min-h-11 min-w-0 rounded-sm border bg-card px-2 font-sans text-xs normal-case tracking-normal text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/30" value={value} onChange={(event) => onChange(event.target.value)}><option value="all">All {label}s</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>;
}
