"use client";

import { Background, Controls, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo, useState } from "react";

import type { ReportRecord } from "@/lib/report-types";

export function SourceGraph({
  onSourceSelect,
  report,
}: {
  onSourceSelect?: (sourceId: string) => void;
  report: ReportRecord;
}) {
  const [relationshipFilter, setRelationshipFilter] = useState("all");
  const [accessFilter, setAccessFilter] = useState("all");
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const relationships = useMemo(
    () => ["all", ...Array.from(new Set(report.sourceGraph.edges.map((edge) => edge.data.relationship)))],
    [report.sourceGraph.edges],
  );

  const visibleNodes = useMemo(
    () =>
      report.sourceGraph.nodes.filter((node) => {
        if (accessFilter === "all") return true;
        return node.data.accessStatus === accessFilter;
      }),
    [accessFilter, report.sourceGraph.nodes],
  );

  const visibleNodeIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const nodes = useMemo<Node[]>(
    () =>
      visibleNodes.map((node) => ({
        id: node.id,
        type: "default",
        position: node.position,
        data: { label: node.label },
        style: node.type === "snapshot" ? { borderStyle: "dashed" } : undefined,
      })),
    [visibleNodes],
  );

  const edges = useMemo<Edge[]>(
    () =>
      report.sourceGraph.edges
        .filter((edge) => relationshipFilter === "all" || edge.data.relationship === relationshipFilter)
        .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
        .map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          animated: edge.data.relationship === "CITES",
        })),
    [relationshipFilter, report.sourceGraph.edges, visibleNodeIds],
  );

  const selectedEdge = report.sourceGraph.edges.find((edge) => edge.id === selectedEdgeId);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-2 rounded-lg border bg-white p-2">
        <select
          className="rounded-md border bg-white px-2 py-1 text-xs"
          value={relationshipFilter}
          onChange={(event) => setRelationshipFilter(event.target.value)}
          aria-label="Filter graph by relationship"
        >
          {relationships.map((relationship) => (
            <option key={relationship} value={relationship}>
              {relationship === "all" ? "All relationships" : relationship}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border bg-white px-2 py-1 text-xs"
          value={accessFilter}
          onChange={(event) => setAccessFilter(event.target.value)}
          aria-label="Filter graph by access status"
        >
          <option value="all">All access states</option>
          <option value="FETCHED">Fetched</option>
          <option value="PAYWALLED">Paywalled</option>
          <option value="INACCESSIBLE">Inaccessible</option>
        </select>
      </div>
      <div className="h-[430px] overflow-hidden rounded-lg border bg-white">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          nodesDraggable={false}
          onEdgeClick={(_, edge) => setSelectedEdgeId(edge.id)}
          onNodeClick={(_, node) => {
            const sourceId = report.sourceGraph.nodes.find((graphNode) => graphNode.id === node.id)?.data.sourceId;
            if (sourceId) onSourceSelect?.(sourceId);
          }}
        >
          <MiniMap pannable zoomable />
          <Controls />
          <Background />
        </ReactFlow>
      </div>
      {selectedEdge && (
        <div className="rounded-lg border bg-white p-3 text-sm">
          <span className="font-semibold">{selectedEdge.data.relationship}</span>
          <span className="ml-2 text-muted-foreground">
            confidence {Math.round(selectedEdge.data.confidence * 100)}% - {selectedEdge.data.detectionMethod}
          </span>
        </div>
      )}
    </div>
  );
}
