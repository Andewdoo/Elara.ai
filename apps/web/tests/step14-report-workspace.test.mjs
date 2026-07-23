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
  for (const label of ["Overview", "Claims", "Evidence", "Graph", "Methodology", "Exact passage"]) assert.match(workspace, new RegExp(label));
  for (const internalDetail of ['id: "calculations"', 'activeReportTab === "calculations"', "Server calculation records", 'title="Methodology"', 'title="Retrieval"', 'title="Models"', 'title="Parsers"']) assert.doesNotMatch(workspace, new RegExp(internalDetail));
  assert.match(workspace, /SourceDrawer/);
  assert.match(charts, /report\.calculations/);
  assert.doesNotMatch(charts, /report\.scores/);
  for (const title of ["Score breakdown", "Evidence balance", "Confidence components", "Research coverage", "Numerical audit"]) assert.match(charts, new RegExp(title));
  for (const label of ["Supporting evidence", "Contradicting evidence", "Attribution support", "Quote fidelity", "Surrounding context"]) assert.match(workspace, new RegExp(label));
  for (const filter of ["atomic claim", "relationship", "source role", "access status", "cluster"]) assert.match(graph, new RegExp(filter));
  assert.match(graph, /evidenceUsed/);
  assert.match(charts, /research_coverage/);
});

test("workspace assigns distinct keys to duplicate limitation text", async () => {
  const workspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  assert.match(workspace, /limitations\.map\(\(item, index\) => <p key=\{`\$\{item\}-\$\{index\}`\}/);
});
