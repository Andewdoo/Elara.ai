import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");

test("history and saved pages use authorized server-owned data", async () => {
  const history = await readFile(join(root, "components", "app", "history-list.tsx"), "utf8");
  assert.match(history, /queryKey: \["history"/);
  assert.match(history, /authenticatedApiFetch/);
  for (const filter of ["query", "status", "sort", "saved_only"]) assert.match(history, new RegExp(filter));
  assert.match(history, /\["COMPLETED", "FAILED", "CANCELLED"\]/);
  for (const removedControl of ["Filter history by research depth", "Filter verdict", "Created from", "Created to"]) assert.doesNotMatch(history, new RegExp(removedControl));
  assert.match(history, /useState<SortField \| null>\(null\)/);
  assert.match(history, /if \(sortField !== field\) setSortField\(field\);/);
  assert.match(history, /overflow-x-auto/);
  assert.match(history, /<table/);
  assert.match(history, /Verification history/);
  assert.match(history, /Saved reports/);
  assert.match(history, /FolderOpen/);
  assert.match(history, /GENERIC_REPORT_TITLES/);
  assert.match(history, /function conciseHistoryTitle/);
  assert.match(history, /historyReportTitle\(item\)/);
  assert.match(history, /Date \{sortField === "date"/);
  assert.match(history, /Confidence \{sortField === "confidence"/);
  assert.match(history, /\/save/);
  assert.match(history, /method: kind === "save" \? "POST" : "DELETE"/);
});

test("report routes use static Demo snapshots before private authenticated endpoints", async () => {
  const reportData = await readFile(join(root, "hooks", "use-report-data.ts"), "utf8");

  assert.match(reportData, /demoArchiveRunResourcePath\(runId, demoResource\)/);
  assert.doesNotMatch(reportData, /\/v1\/demo-runs/);
  assert.match(reportData, /\/v1\/verifications\/\$\{runId\}/);
  assert.match(reportData, /if \(!user\) throw new Error\("Sign in to view this report\."\)/);
});

test("report controls expose all feedback categories and private JSON export flow", async () => {
  const controls = await readFile(join(root, "components", "report", "report-actions.tsx"), "utf8");
  const hook = await readFile(join(root, "hooks", "use-report-actions.ts"), "utf8");
  for (const category of ["CORRECTION", "MISSED_EVIDENCE", "APPEAL", "BROKEN_CITATION"]) assert.match(controls, new RegExp(category));
  assert.match(hook, /\/feedback/);
  assert.match(hook, /\/exports/);
  assert.match(hook, /download_url/);
  assert.doesNotMatch(hook, /S3_|access_key|secret/i);
  assert.match(controls, /useForm/);
  assert.match(controls, /zodResolver/);
  assert.match(controls, /feedbackSchema/);
});
