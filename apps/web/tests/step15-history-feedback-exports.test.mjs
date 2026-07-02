import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");

test("history and saved pages use authorized server-owned data", async () => {
  const history = await readFile(join(root, "components", "app", "history-list.tsx"), "utf8");
  assert.match(history, /queryKey: \["history"/);
  assert.match(history, /authenticatedApiFetch/);
  for (const filter of ["query", "status", "research_depth", "sort", "saved_only"]) assert.match(history, new RegExp(filter));
  assert.match(history, /\/save/);
  assert.match(history, /method: kind === "save" \? "POST" : "DELETE"/);
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
