import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("run events use credentialed EventSource without URL tokens", async () => {
  const hook = await read("../hooks/use-run-events.ts");
  assert.match(hook, /new EventSource/);
  assert.match(hook, /withCredentials: true/);
  assert.match(hook, /invalidateQueries\(\{ queryKey: \["run", runId\]/);
  assert.match(hook, /invalidateQueries\(\{ queryKey: \["report", runId\]/);
  assert.match(hook, /pollingFallback.*3_000/s);
  assert.match(hook, /invalidatedTerminalResult/);
  assert.match(hook, /JSON\.parse[\s\S]*catch[\s\S]*reconnectOrPoll/);
  assert.doesNotMatch(hook, /[?&](token|id_token|session)=/i);
});

test("live view exposes required public progress controls", async () => {
  const view = await read("../components/app/live-research-view.tsx");
  const hook = await read("../hooks/use-run-events.ts");
  assert.match(hook, /completed_steps/);
  assert.match(hook, /source_counts/);
  assert.match(hook, /inaccessible_count/);
  assert.match(view, /const researchStages/);
  assert.match(view, /Auditing citations/);
  assert.match(view, /Verification research stages/);
  assert.match(view, /progressHistoryQuery/);
  assert.match(view, /CircleCheck/);
  assert.match(view, /index \+ 1 < completedSteps/);
  assert.match(view, /workflow\.evidence_classification\./);
  assert.match(view, /Classifying evidence/);
  assert.match(view, /workflow\.deterministic_scoring\./);
  assert.match(view, /Calculating scores/);
  assert.match(view, /workflow\.numerical_audit\./);
  assert.match(view, /Auditing calculations/);
  assert.match(view, /durableTerminal[\s\S]*failure_message/);
  assert.match(hook, /\["run-progress", runId\]/);
  assert.match(hook, /\/v1\/verifications\/\$\{runId\}\/progress/);
  assert.match(view, /Cancel research/);
  assert.doesNotMatch(view, /Polling PostgreSQL|Latest public event|Run \{runId\}/);
  assert.doesNotMatch(view, /DeepSeek|prompt_version|schema_error|passage_id/i);
});
