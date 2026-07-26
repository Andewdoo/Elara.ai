import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("Lite output renders through the shared Full Mode report workspace", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");
  const reportWorkspace = await read("components", "report", "report-workspace.tsx");

  assert.match(workspace, /ReportWorkspace/);
  assert.match(workspace, /liteResponseToReportWorkspace/);
  assert.match(reportWorkspace, /mode = "full"/);
  assert.match(reportWorkspace, /Curated Lite library/);
  assert.match(reportWorkspace, /xl:grid-cols-\[260px_minmax\(0,1fr\)_340px\]/);
  assert.match(reportWorkspace, /fixed inset-0 z-50/);
});

test("Lite adapter maps cited sentences and exact source chunks into report records", async () => {
  const adapter = await read("lib", "lite", "report-adapter.ts");
  const reportWorkspace = await read("components", "report", "report-workspace.tsx");

  assert.match(adapter, /cited_sentences/);
  assert.match(adapter, /report_sentences/);
  assert.match(adapter, /passage_id: sentence\.citation_ids\[0\]/);
  assert.match(adapter, /chunk\.chunk_text/);
  assert.match(reportWorkspace, /Cited answer/);
  assert.match(reportWorkspace, /Exact source chunk - Cited sentences/);
  assert.match(reportWorkspace, /Chunk metadata/);
});

test("Lite adapter preserves insufficient-evidence state without Full Mode score output", async () => {
  const adapter = await read("lib", "lite", "report-adapter.ts");
  const reportWorkspace = await read("components", "report", "report-workspace.tsx");

  assert.match(adapter, /Insufficient evidence in Lite library/);
  assert.match(adapter, /response\.kind === "insufficient_evidence" \? response\.message/);
  assert.match(adapter, /calculations: \[\]/);
  assert.match(adapter, /scores: \{\}/);
  assert.match(reportWorkspace, /!\s*isLite && <ScoreCharts/);
  assert.match(reportWorkspace, /isLite \? "Lite result" : "Verdict"/);
});

test("Lite report metadata exposes corpus, model, prompt, and curated-library scope", async () => {
  const adapter = await read("lib", "lite", "report-adapter.ts");
  const reportWorkspace = await read("components", "report", "report-workspace.tsx");

  assert.match(adapter, /Corpus version:/);
  assert.match(adapter, /model_versions: response\.report_metadata\.model_versions/);
  assert.match(adapter, /prompt_versions: response\.report_metadata\.prompt_versions/);
  assert.match(adapter, /retrieval_strategy_version/);
  assert.match(adapter, /curated Lite evidence library/);
  assert.match(reportWorkspace, /Evidence reviewed as of/);
  assert.match(reportWorkspace, /workspace_scope/);
  assert.match(reportWorkspace, /Version title="AI Pipeline" value=\{report\.prompt_versions\}/);
});
