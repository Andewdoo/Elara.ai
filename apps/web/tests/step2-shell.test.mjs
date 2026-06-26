import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = fileURLToPath(new URL("..", import.meta.url));

test("Firebase browser shell only references approved public Firebase env vars", async () => {
  const firebaseSource = await readFile(join(root, "lib", "firebase.ts"), "utf8");
  const allowed = [
    "NEXT_PUBLIC_FIREBASE_API_KEY",
    "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN",
    "NEXT_PUBLIC_FIREBASE_PROJECT_ID",
    "NEXT_PUBLIC_FIREBASE_APP_ID",
  ];
  const forbidden = [
    "FIREBASE_CLIENT_EMAIL",
    "FIREBASE_PRIVATE_KEY",
    "DEEPSEEK_API_KEY",
    "SEARCH_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "S3_SECRET_ACCESS_KEY",
    "SENTRY_AUTH_TOKEN",
    "LANGSMITH_API_KEY",
  ];

  for (const name of allowed) {
    assert.match(firebaseSource, new RegExp(name));
  }
  for (const name of forbidden) {
    assert.doesNotMatch(firebaseSource, new RegExp(name));
  }
});

test("mocked report includes the required evidence reviewed timestamp text", async () => {
  const reportSource = await readFile(join(root, "lib", "mock-report.ts"), "utf8");

  assert.match(reportSource, /Evidence reviewed as of/);
  assert.match(reportSource, /New evidence or corrections may change this assessment\./);
  assert.match(reportSource, /inaccessibleSources/);
  assert.match(reportSource, /calculations/);
  assert.match(reportSource, /methodology/);
  assert.match(reportSource, /Attribution Support/);
  assert.match(reportSource, /Quote Fidelity/);
  assert.match(reportSource, /type: "snapshot"/);
});

test("report shell includes planned route and workspace surfaces", async () => {
  const routeFiles = [
    "app/page.tsx",
    "app/methodology/page.tsx",
    "app/verify/page.tsx",
    "app/verify/[runId]/page.tsx",
    "app/report/[runId]/page.tsx",
    "app/history/page.tsx",
    "app/saved/page.tsx",
    "app/settings/page.tsx",
    "app/api/.gitkeep",
  ];

  for (const routeFile of routeFiles) {
    const source = await readFile(join(root, routeFile), "utf8");
    assert.equal(typeof source, "string");
  }

  const reportWorkspace = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");
  const sourceGraph = await readFile(join(root, "components", "report", "source-graph.tsx"), "utf8");
  const verifyForm = await readFile(join(root, "components", "app", "verify-form.tsx"), "utf8");

  assert.match(reportWorkspace, /Feedback and correction controls/);
  assert.match(reportWorkspace, /Cited passages/);
  assert.match(sourceGraph, /onNodeClick/);
  assert.match(sourceGraph, /onEdgeClick/);
  assert.doesNotMatch(verifyForm, /window\.location/);
});
