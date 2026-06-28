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
  assert.match(view, /completed_steps/);
  assert.match(view, /source_counts/);
  assert.match(view, /inaccessible_count/);
  assert.match(view, /Cancel research/);
  assert.match(view, /Latest public event/);
});
