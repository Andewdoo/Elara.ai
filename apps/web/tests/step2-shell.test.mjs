import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = fileURLToPath(new URL("..", import.meta.url));

async function readSourceFiles(dir, files = []) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (path.endsWith(join("app", "api"))) continue;
      await readSourceFiles(path, files);
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry.name)) files.push(path);
  }
  return files;
}

test("Firebase browser shell only references approved public Firebase env vars", async () => {
  const firebaseSource = await readFile(join(root, "lib", "firebase.ts"), "utf8");
  const layoutSource = await readFile(join(root, "app", "layout.tsx"), "utf8");
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
    assert.match(layoutSource, new RegExp(name));
  }
  for (const name of forbidden) {
    assert.doesNotMatch(firebaseSource, new RegExp(name));
    assert.doesNotMatch(layoutSource, new RegExp(name));
  }
});

test("Lite browser surface only references public env and never service-role access", async () => {
  const browserRoots = ["app", "components", "hooks", "stores"];
  const files = (await Promise.all(browserRoots.map((dir) => readSourceFiles(join(root, dir)).catch(() => [])))).flat();
  files.push(join(root, "lib", "auth.ts"), join(root, "lib", "firebase.ts"), join(root, "lib", "utils.ts"));
  const browserSource = (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n");
  const envReferences = Array.from(browserSource.matchAll(/process\.env\.([A-Z0-9_]+)/g), (match) => match[1]);
  const allowedPublicLiteEnv = [
    "NEXT_PUBLIC_ELARA_MODE",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_FIREBASE_API_KEY",
    "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN",
    "NEXT_PUBLIC_FIREBASE_PROJECT_ID",
    "NEXT_PUBLIC_FIREBASE_APP_ID",
  ];
  const forbiddenServerEnv = [
    "SUPABASE_SERVICE_ROLE_KEY",
    "DEEPSEEK_API_KEY",
    "SEARCH_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "S3_SECRET_ACCESS_KEY",
    "FIREBASE_PRIVATE_KEY",
    "FIREBASE_CLIENT_EMAIL",
    "SENTRY_AUTH_TOKEN",
    "LANGSMITH_API_KEY",
  ];

  for (const name of allowedPublicLiteEnv) {
    assert.match(await readFile(join(root, "..", "..", ".env.example"), "utf8"), new RegExp(`${name}=`));
  }
  for (const name of envReferences) {
    assert.match(name, /^NEXT_PUBLIC_/);
  }
  for (const name of forbiddenServerEnv) {
    assert.doesNotMatch(browserSource, new RegExp(`process\\.env\\.${name}\\b`));
  }
  assert.doesNotMatch(browserSource, /SUPABASE_SERVICE_ROLE_KEY/);
  assert.doesNotMatch(browserSource, /service-role|serviceRole|service_role/i);
});

test("report workspace includes the required evidence-reviewed timestamp language", async () => {
  const reportSource = await readFile(join(root, "components", "report", "report-workspace.tsx"), "utf8");

  assert.match(reportSource, /Evidence reviewed as of/);
  assert.match(reportSource, /New evidence or corrections may change this assessment\./);
  assert.match(reportSource, /limitations/);
  assert.match(reportSource, /calculations/);
  assert.match(reportSource, /methodology/);
  assert.match(reportSource, /Attribution support/);
  assert.match(reportSource, /Quote fidelity/);
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
