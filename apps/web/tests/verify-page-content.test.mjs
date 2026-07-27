import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const verifyPagePath = new URL("../app/verify/page.tsx", import.meta.url);

test("verification page delegates active-run recovery to the Verify route", async () => {
  const source = await readFile(verifyPagePath, "utf8");

  assert.match(source, /VerifyRoute/);
  assert.match(source, /return <VerifyRoute \/>;/);
  assert.doesNotMatch(source, /Submission boundaries|ShieldCheck|Browser validation is a convenience layer/);
});
