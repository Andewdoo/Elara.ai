import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";

import { snapshotDemoArchive, validateBundledDemoArchive } from "../scripts/snapshot-demo-archive.mjs";

const runId = "01990f2a-6540-7000-8000-000000000001";

function response(value) {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}

function archiveResponses(auditStatus = "passed") {
  const item = {
    run_id: runId,
    status: "COMPLETED",
    input_type: "CLAIM",
    research_depth: "STANDARD",
    title: "Audited public Demo report",
    submitted_text_preview: "A designated public claim",
    verdict: "SUPPORTED",
    verdict_confidence: 90,
    evidence_reviewed_at: "2026-08-31T12:00:00Z",
    created_at: "2026-08-31T11:00:00Z",
    updated_at: "2026-08-31T12:00:00Z",
    saved_at: null,
  };
  return new Map([
    ["/v1/demo-runs", { items: [item], total: 1, page: 1, page_size: 12 }],
    [`/v1/demo-runs/${runId}`, { ...item, queued_at: item.created_at, started_at: item.created_at, completed_at: item.updated_at, failed_at: null, cancellation_requested_at: null, failure_code: null, failure_message: null, is_owner: false, publication_state: "published", publication_review_reason: null }],
    [`/v1/demo-runs/${runId}/report`, { run_id: runId, evidence_reviewed_at: item.evidence_reviewed_at, report_sentences: [{ id: "citation-1", audit_status: auditStatus }] }],
    [`/v1/demo-runs/${runId}/sources`, { sources: [{ id: "source-1", passages: [{ id: "passage-1", text: "Exact evidence." }] }] }],
    [`/v1/demo-runs/${runId}/source-graph`, { nodes: [], edges: [] }],
  ]);
}

function fetchFrom(responses) {
  return async (url) => {
    const path = new URL(url).pathname;
    return responses.has(path) ? response(responses.get(path)) : new Response("missing", { status: 404 });
  };
}

test("snapshot command materializes the complete public Demo archive for Vercel", async () => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "elara-demo-archive-"));
  const outputDir = join(temporaryRoot, "demo-archive");
  try {
    const result = await snapshotDemoArchive({
      apiBaseUrl: "https://api.example.test",
      outputDir,
      expectedCount: 1,
      fetchImpl: fetchFrom(archiveResponses()),
      generatedAt: new Date("2026-09-01T12:00:00Z"),
    });

    assert.equal(result.count, 1);
    const manifest = JSON.parse(await readFile(join(outputDir, "manifest.json"), "utf8"));
    assert.equal(manifest.schema_version, 1);
    assert.equal(manifest.generated_at, "2026-09-01T12:00:00.000Z");
    assert.deepEqual(manifest.items.map((item) => item.run_id), [runId]);
    for (const resource of ["run", "report", "sources", "source-graph"]) {
      assert.ok(JSON.parse(await readFile(join(outputDir, "runs", runId, `${resource}.json`), "utf8")));
    }
    assert.equal((await validateBundledDemoArchive({ outputDir, expectedCount: 1 })).count, 1);
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("bundled archive validation fails when a report resource is absent", async () => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "elara-demo-archive-"));
  const outputDir = join(temporaryRoot, "demo-archive");
  try {
    await snapshotDemoArchive({
      apiBaseUrl: "https://api.example.test",
      outputDir,
      expectedCount: 1,
      fetchImpl: fetchFrom(archiveResponses()),
    });
    await rm(join(outputDir, "runs", runId, "report.json"));

    await assert.rejects(
      validateBundledDemoArchive({ outputDir, expectedCount: 1 }),
      /bundled Demo archive is missing or malformed/,
    );
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("snapshot command fails closed when a designated report has a failing citation audit", async () => {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "elara-demo-archive-"));
  const outputDir = join(temporaryRoot, "demo-archive");
  try {
    await assert.rejects(
      snapshotDemoArchive({
        apiBaseUrl: "https://api.example.test",
        outputDir,
        expectedCount: 1,
        fetchImpl: fetchFrom(archiveResponses("failed")),
      }),
      /contains a failing citation audit/,
    );
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
});
