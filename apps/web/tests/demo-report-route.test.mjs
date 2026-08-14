import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("demo cards open reports inside the dedicated Demo route", async () => {
  const workspace = await read("components", "demo", "demo-workspace.tsx");
  const page = await read("app", "demo", "report", "[runId]", "page.tsx");

  assert.match(workspace, /href=\{`\/demo\/report\/\$\{run\.run_id\}`\}/);
  assert.match(page, /<ReportRoute runId=\{runId\} demoOnly \/>/);
});

test("demo reports retain Demo chrome and do not render the verifier sidebar", async () => {
  const shell = await read("components", "app", "app-shell.tsx");

  assert.match(shell, /pathname\.startsWith\("\/demo\/report\/"\)/);
  assert.match(shell, /const isDemo = pathname === "\/" \|\| isDemoReport/);
  assert.match(shell, /Back to Demo archive/);
  assert.match(shell, /isDemoReport \? "max-w-7xl" : "max-w-5xl"/);
});

test("demo-only report data never falls back to private verifier endpoints", async () => {
  const hook = await read("hooks", "use-report-data.ts");

  assert.match(hook, /if \(demoOnly\) throw new Error\(await apiErrorMessage\(demoResponse\)\)/);
  assert.match(hook, /const queryScope = demoOnly \? "demo"/);
  assert.match(hook, /authenticated: demoOnly \|\| Boolean\(user\)/);
});
