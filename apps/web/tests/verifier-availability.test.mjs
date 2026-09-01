import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Full Verifier checks backend availability and handles gateway failures", async () => {
  const form = await read("../components/app/verify-form.tsx");

  assert.match(form, /fetch\(`\$\{apiBaseUrl\}\/health`/);
  assert.match(form, /VERIFIER_AVAILABILITY_TIMEOUT_MS = 4_000/);
  assert.match(form, /new Set\(\[502, 503, 504\]\)/);
  assert.match(form, /setUnavailableOpen\(true\)/);
  assert.match(form, /<VerifierUnavailableDialog/);
});

test("unavailable dialog gives the daily ET window and a Demo archive recovery path", async () => {
  const dialog = await read("../components/app/verifier-unavailable-dialog.tsx");

  assert.match(dialog, /Full Verifier is currently unavailable/);
  assert.match(dialog, /9:00 AM–9:00 PM ET/);
  assert.match(dialog, /sorry for the inconvenience/);
  assert.match(dialog, /href="\/"/);
  assert.match(dialog, /View Demo archive/);
  assert.match(dialog, /aria-labelledby="verifier-unavailable-title"/);
  assert.match(dialog, /aria-describedby="verifier-unavailable-description"/);
  assert.match(dialog, /showModal\(\)/);
});
