import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("reports always initialize on Overview", async () => {
  const workspace = await read("components", "report", "report-workspace.tsx");

  assert.match(workspace, /useState<ReportTab>\("overview"\)/);
  assert.match(workspace, /key=\{data\.run\.run_id\}/);
});

test("Verify restores only an active in-memory run and otherwise shows an empty form", async () => {
  const route = await read("components", "app", "verify-route.tsx");
  const store = await read("stores", "active-verification-store.ts");
  const form = await read("components", "app", "verify-form.tsx");

  assert.match(route, /state\.isActive \? state\.runId : null/);
  assert.match(route, /<LiveResearchView runId=\{activeRunId\} \/>/);
  assert.match(route, /<VerifyForm \/>/);
  assert.match(form, /resumeVerification\(created\.run_id\)/);
  assert.match(store, /Intentionally in-memory only/);
  assert.match(store, /latestEvent: RunProgressEvent \| null/);
});

test("run progress hydrates durable history without regressing the latest server event", async () => {
  const hook = await read("hooks", "use-run-events.ts");
  const store = await read("stores", "active-verification-store.ts");
  const live = await read("components", "app", "live-research-view.tsx");

  assert.match(hook, /state\.runId === runId \? state\.latestEvent : null/);
  assert.match(hook, /\["run-progress", runId\]/);
  assert.match(hook, /\/v1\/verifications\/\$\{runId\}\/progress/);
  assert.match(hook, /recordProgress\(progress\)/);
  assert.match(store, /function isNewerProgress/);
  assert.match(store, /event\.completed_steps >= current\.completed_steps/);
  assert.match(live, /const researchStages/);
  assert.match(live, /Verification research stages/);
  assert.match(live, /progressHistoryQuery/);
});

test("primary navigation calls the Lite workspace Lite mode and places it last", async () => {
  const shell = await read("components", "app", "app-shell.tsx");
  const labels = [...shell.matchAll(/label: "([^"]+)"/g)].map((match) => match[1]);

  assert.deepEqual(labels, ["Verify", "History", "Saved", "Methodology", "Lite mode"]);
  assert.doesNotMatch(shell, /label: "Workspace"|label: "Workplace"/);
});
