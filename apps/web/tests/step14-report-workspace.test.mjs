import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");

test("report route uses authenticated API-backed TanStack queries", async () => {
  const route = await readFile(join(root, "components", "report", "report-route.tsx"), "utf8");
  const hook = await readFile(join(root, "hooks", "use-report-data.ts"), "utf8");
  assert.doesNotMatch(route, /useMockedReport|mock-report/);
  for (const key of ["run", "report", "sources", "source-graph"]) assert.match(hook, new RegExp(`queryKey: \\[\"${key}`));
  assert.match(hook, /authenticatedApiFetch/);
});

test("workspace exposes user-facing tabs, exact passages, graph, and score charts", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  const charts = await readFile(join(root, "components", "report", "score-charts.tsx"), "utf8");
  const graph = await readFile(join(root, "components", "report", "source-graph.tsx"), "utf8");
  for (const label of ["Overview", "Claims", "Evidence", "Graph", "Exact passage"]) assert.match(workspace, new RegExp(label));
  for (const internalDetail of ['id: "calculations"', 'activeReportTab === "calculations"', "Server calculation records", 'title="Methodology"', 'title="Retrieval"', 'title="Models"', 'title="Parsers"']) assert.doesNotMatch(workspace, new RegExp(internalDetail));
  for (const sourceDetail of ["Parser", "Content hash", "Snapshot metadata", "Passage metadata", "Chunk metadata", "source.retrieval_reason"]) assert.doesNotMatch(workspace, new RegExp(sourceDetail));
  assert.doesNotMatch(workspace, /\["Snapshot", source\.snapshot_id/);
  assert.match(workspace, /SourceDrawer/);
  assert.match(charts, /report\.calculations/);
  assert.doesNotMatch(charts, /report\.scores/);
  for (const title of ["Score breakdown", "Evidence balance", "Confidence components", "Research coverage"]) assert.match(charts, new RegExp(title));
  assert.doesNotMatch(charts, /Numerical audit/);
  for (const label of ["Supporting evidence", "Contradicting evidence", "Attribution support", "Quote fidelity", "Surrounding context"]) assert.match(workspace, new RegExp(label));
  for (const filter of ["atomic claim", "relationship", "source role", "access status", "cluster"]) assert.match(graph, new RegExp(filter));
  assert.match(graph, /evidenceUsed/);
  assert.match(graph, /Graph links/);
  assert.match(graph, /<details/);
  for (const graphControl of ["Find a source", "Used in report", "Fit view", "Full screen", "Reset filters", "Selected node"]) assert.match(graph, new RegExp(graphControl));
  for (const preservedBehavior of ["onNodeClick", "onEdgeClick", "onSourceSelect", "Accessible source graph summary", "Graph summary"]) assert.match(graph, new RegExp(preservedBehavior));
  assert.match(graph, /fixed inset-0 z-50 h-dvh/);
  assert.match(graph, /event\.key === "Escape"/);
  assert.match(graph, /document\.body\.style\.overflow = "hidden"/);
  assert.match(graph, /panOnDrag/);
  assert.match(graph, /minZoom: isFullscreen \? 0\.68 : 0\.48/);
  assert.match(graph, /h-\[calc\(100dvh-15rem\)\] min-h-\[720px\]/);
  assert.match(graph, /\{ x: 610, y: snapshotY/);
  assert.match(graph, /\{ x: 280, y: sourceY/);
  assert.doesNotMatch(graph, /<MiniMap/);
  assert.doesNotMatch(graph, /<Controls/);
  assert.match(graph, /layoutGraphNodes/);
  assert.match(graph, /getSourceNodeId/);
  assert.doesNotMatch(workspace, /Report details/);
  assert.match(charts, /research_coverage/);
  assert.match(workspace, /claimLabelTone/);
  assert.match(workspace, /!normalized\.startsWith\("insufficient evidence"\)/);
});

test("workspace assigns distinct keys to duplicate limitation text", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  assert.match(workspace, /limitations\.map\(\(item, index\) => <p key=\{`\$\{item\}-\$\{index\}`\}/);
});

test("report redesign keeps the ledger layout responsive and hydration-stable", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  const charts = await readFile(join(root, "components", "report", "score-charts.tsx"), "utf8");
  const styles = await readFile(join(root, "app", "globals.css"), "utf8");

  assert.match(workspace, /report-ledger/);
  assert.match(workspace, /font-editorial/);
  assert.match(workspace, /min-h-11/);
  assert.match(workspace, /reportDateTimeFormat/);
  assert.match(workspace, /timeZone: "UTC"/);
  assert.match(charts, /<div className="sr-only"><table>/);
  assert.match(styles, /\.report-ledger/);
  assert.match(styles, /prefers-reduced-motion: reduce/);
});

test("workspace groups every supported stored evidence stance without browser-side inference", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  const evidence = await readFile(join(root, "lib", "report-evidence.ts"), "utf8");

  for (const stance of ["STRONGLY_SUPPORTS", "PARTIALLY_SUPPORTS", "STRONGLY_CONTRADICTS", "PARTIALLY_CONTRADICTS", "NEUTRAL"]) {
    assert.match(evidence, new RegExp(stance));
  }
  assert.match(evidence, /typeof stance === "string"/);
  assert.doesNotMatch(evidence, /\.includes\(/);
  assert.match(workspace, /groupEvidenceByStance\(report\.evidence\)/);
  assert.match(workspace, /Evidence data needs review/);
  assert.match(workspace, /<option value="neutral">Neutral<\/option>/);
  assert.match(workspace, /invalid\.length < report\.evidence\.length/);
});

test("desktop source drawer is viewport-bounded and does not stretch with report content", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");

  assert.match(workspace, /grid min-w-0 items-start bg-card/);
  assert.match(workspace, /xl:static xl:z-auto xl:max-h-\[calc\(100dvh-3rem\)\] xl:min-h-0 xl:self-start/);
});

test("graph tab uses its internal inspector without the report source drawer", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");

  assert.match(workspace, /const showSourceDrawer = activeReportTab !== "graph" && ui\.sourceDrawerOpen/);
  assert.match(workspace, /activeReportTab !== "graph" && \(/);
  assert.match(workspace, /showSourceDrawer && <SourceDrawer/);
});
