import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("default route renders the Lite evidence-library workspace first", async () => {
  const page = await read("app", "page.tsx");
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(page, /LiteWorkspace/);
  assert.doesNotMatch(page, /VerifyForm|HistoryList|StatusStrip/);
  assert.match(workspace, /Lite evidence library/);
  assert.match(workspace, /New Lite report/);
  assert.match(workspace, /Claim or question/);
  assert.match(workspace, /Report progress/);
  assert.match(workspace, /Report workspace/);
});

test("Lite default page exposes a clear Full Mode route", async () => {
  const workspace = await read("components", "lite", "lite-workspace.tsx");

  assert.match(workspace, /href="\/verify"/);
  assert.match(workspace, /Open Full Verifier/);
});

test("Lite default page labels scope without exposing secret environment names", async () => {
  const renderedSources = [
    await read("app", "page.tsx"),
    await read("components", "lite", "lite-workspace.tsx"),
  ].join("\n");

  assert.match(renderedSources, /curated stored evidence library/i);
  assert.match(renderedSources, /not the complete production verifier/i);

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
