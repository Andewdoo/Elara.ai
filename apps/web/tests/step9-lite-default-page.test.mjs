import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("default route renders the read-only Demo archive", async () => {
  const page = await read("app", "page.tsx");
  const workspace = await read("components", "demo", "demo-workspace.tsx");
  const runs = await read("lib", "demo", "demo-runs.ts");

  assert.match(page, /DemoWorkspace/);
  assert.doesNotMatch(page, /VerifyForm|HistoryList|StatusStrip/);
  assert.match(workspace, /Read-only demo archive/);
  assert.match(workspace, /Completed verification runs/);
  assert.match(
    workspace,
    /This Demo displays 12 citation-audited full-version reports\. It does not accept requests or retrieve new evidence\./,
  );
  assert.match(runs, /DEMO_RUN_LIMIT = 12/);
});

test("Demo uses the shared, designated full-version reports", async () => {
  const workspace = await read("components", "demo", "demo-workspace.tsx");

  assert.match(workspace, /fetch\(`\$\{apiBaseUrl\}\/v1\/demo-runs`\)/);
  assert.doesNotMatch(workspace, /authenticatedApiFetch|useFirebaseAuth|saved_only|\/v1\/history/);
  assert.match(workspace, /href="\/verify"/);
  assert.match(workspace, /Open Full Verifier/);
  assert.match(workspace, /href=\{`\/demo\/report\/\$\{run\.run_id\}`\}/);
  assert.match(workspace, /grid-cols-3[\s\S]*sm:w-\[27rem\]/);
  assert.doesNotMatch(workspace, /api\/lite|textarea|<form/i);
});

test("Demo labels its scope without exposing secret environment names", async () => {
  const renderedSources = [
    await read("app", "page.tsx"),
    await read("components", "demo", "demo-workspace.tsx"),
    await read("lib", "demo", "demo-runs.ts"),
  ].join("\n");

  assert.match(renderedSources, /citation-audited full-version reports/i);
  assert.match(renderedSources, /designated shared report collection/i);

  for (const forbidden of [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "S3_SECRET_ACCESS_KEY",
    "FIREBASE_PRIVATE_KEY",
    "FIREBASE_CLIENT_EMAIL",
    "SEARCH_API_KEY",
  ]) {
    assert.doesNotMatch(renderedSources, new RegExp(forbidden));
  }
});
