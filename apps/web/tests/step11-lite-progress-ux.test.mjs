import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("Lite progress mirrors Full Mode stage language without claiming worker execution", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  for (const stage of [
    "Intake",
    "Query planning",
    "Library retrieval",
    "Evidence review",
    "Synthesis",
    "Citation audit",
  ]) {
    assert.match(workspace, new RegExp(stage));
  }

  assert.match(workspace, /request-local progress/i);
  assert.match(workspace, /one server-side answer request returns the final typed response/i);
  assert.doesNotMatch(workspace, /EventSource|Redis|Celery|worker execution|background worker/i);
});

test("Lite loading state advances an optimistic local timeline during the single answer request", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(workspace, /useEffect\(\(\) => \{/);
  assert.match(workspace, /setInterval\(\(\) => \{/);
  assert.match(workspace, /setActiveStageIndex\(\(stageIndex\) => Math\.min\(stageIndex \+ 1, finalOptimisticStageIndex\)\)/);
  assert.match(workspace, /fetch\("\/api\/lite\/answer"/);
  assert.match(workspace, /aria-label="Lite request progress"/);
  assert.match(workspace, /progressStatus === "loading"/);
  assert.match(workspace, /<Loader2 className="h-4 w-4 animate-spin"/);
});

test("Lite success and failure states terminate the progress timeline explicitly", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(workspace, /setProgressStatus\("success"\)/);
  assert.match(workspace, /setActiveStageIndex\(finalOptimisticStageIndex\)/);
  assert.match(workspace, /setProgressStatus\("failure"\)/);
  assert.match(workspace, /Citation-audited Lite report is ready/);
  assert.match(workspace, /Lite request stopped before a typed report was completed/);
  assert.match(workspace, /Needs retry/);
});

test("Lite retry resubmits the last bounded request payload", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(workspace, /const \[lastSubmission, setLastSubmission\]/);
  assert.match(workspace, /setLastSubmission\(\{ input: trimmed \}\)/);
  assert.match(workspace, /function retryLiteRequest\(\)/);
  assert.match(workspace, /void runLiteRequest\(retrySubmission\)/);
  assert.match(workspace, />\s*Retry\s*</);
  assert.match(workspace, /<RefreshCw className="h-4 w-4"/);
});

test("Lite cancellation and clear behavior abort the request and reset transient state", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(workspace, /const abortControllerRef = useRef<AbortController \| null>\(null\)/);
  assert.match(workspace, /signal: controller\.signal/);
  assert.match(workspace, /function cancelLiteRequest\(\)/);
  assert.match(workspace, /abortControllerRef\.current\?\.abort\(\)/);
  assert.match(workspace, /setProgressStatus\("cancelled"\)/);
  assert.match(workspace, /No background Lite worker is running/);
  assert.match(workspace, /function clearLiteWorkspace\(\)/);
  assert.match(workspace, /setInput\(""\)/);
  assert.match(workspace, /setProgressStatus\("idle"\)/);
  assert.match(workspace, />\s*Clear\s*</);
});
