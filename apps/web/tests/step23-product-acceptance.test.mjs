import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("production routes contain no sample submissions, mock badges, fabricated telemetry, or inert settings", async () => {
  const files = await Promise.all([
    read("app", "page.tsx"), read("app", "settings", "page.tsx"),
    read("app", "methodology", "page.tsx"), read("components", "app", "status-strip.tsx"),
    read("components", "app", "verify-form.tsx"),
  ]);
  const production = files.join("\n");
  assert.doesNotMatch(production, /Mock setting|Citywide transit|1 inaccessible source|App shell|version 1\.0 shell|later worker step/i);
  assert.match(files[4], /target: ""/);
});

test("report tabs, mobile drawer, charts, graph, and forms expose keyboard and accessibility semantics", async () => {
  const workspace = await read("components", "report", "report-workspace.tsx");
  const charts = await read("components", "report", "score-charts.tsx");
  const graph = await read("components", "report", "source-graph.tsx");
  const feedback = await read("components", "report", "report-actions.tsx");
  const auth = await read("components", "app", "auth-controls.tsx");
  for (const token of ['role="tablist"', 'role="tab"', "aria-selected", "ArrowRight", "ArrowLeft", 'role="tabpanel"']) assert.match(workspace, new RegExp(token));
  for (const token of ['role="dialog"', "aria-modal", "Escape", "event.key !== \"Tab\"", "previousFocusRef"]) assert.match(workspace, new RegExp(token));
  assert.match(charts, /AccessibleTable/);
  assert.match(graph, /Accessible source graph summary/);
  assert.match(workspace, /fixed inset-0[\s\S]*xl:static/);
  assert.match(workspace, /md:grid-cols-3/);
  assert.match(feedback, /aria-describedby/);
  assert.match(auth, /htmlFor="auth-email"/);
});

test("reconnect, retry, refresh, cancellation, route recovery, and partial report resources are actionable", async () => {
  const live = await read("components", "app", "live-research-view.tsx");
  const events = await read("hooks", "use-run-events.ts");
  const history = await read("components", "app", "history-list.tsx");
  const route = await read("components", "report", "report-route.tsx");
  const boundary = await read("app", "global-error.tsx");
  for (const token of ['role="progressbar"', 'aria-live="polite"', "Retry verification", "Cancel research", "Refresh"]) assert.match(live, new RegExp(token));
  assert.match(events, /\/retry/);
  assert.match(history, /item.status === "COMPLETED" \? `\/report/);
  assert.match(route, /resourceFailures/);
  assert.match(route, /Retry loading/);
  assert.match(boundary, /reset/);
});

test("report renders every sentence role, user-facing report details, durable histories, and empty states", async () => {
  const workspace = await read("components", "report", "report-workspace.tsx");
  const actions = await read("components", "report", "report-actions.tsx");
  const hook = await read("hooks", "use-report-actions.ts");
  for (const token of ["factual_finding", "attribution", "strongest_contradiction", "score_roles", "generated_at", "No inaccessible sources"]) assert.match(workspace, new RegExp(token));
  for (const internalDetail of ['id: "calculations"', 'activeReportTab === "calculations"', "Server calculation records", 'title="Methodology"', 'title="Retrieval"', 'title="Models"', 'title="Parsers"']) assert.doesNotMatch(workspace, new RegExp(internalDetail));
  assert.match(actions, /Download prepared JSON/);
  assert.match(actions, /Feedback status history/);
  assert.match(hook, /queryKey: \["exports"/);
  assert.match(hook, /queryKey: \["feedback"/);
});
