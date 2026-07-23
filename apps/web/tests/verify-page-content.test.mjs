import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const verifyPagePath = new URL("../app/verify/page.tsx", import.meta.url);

test("verification page contains only the verification form", async () => {
  const source = await readFile(verifyPagePath, "utf8");

  assert.match(source, /return <VerifyForm \/>;/);
  assert.doesNotMatch(source, /Submission boundaries|ShieldCheck|Browser validation is a convenience layer/);
});
