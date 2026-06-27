import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Firebase web auth exchanges tokens in headers and never in URLs", async () => {
  const auth = await read("../lib/auth.ts");

  assert.match(auth, /Authorization.*Bearer/);
  assert.match(auth, /credentials: "include"/);
  assert.match(auth, /Array\.isArray\(body\?\.detail\)/);
  assert.match(auth, /if \(!response\.ok\)/);
  assert.doesNotMatch(auth, /[?&](token|id_token|session)=/i);
  assert.doesNotMatch(auth, /FIREBASE_(CLIENT_EMAIL|PRIVATE_KEY)/);
  assert.doesNotMatch(auth, new RegExp(["OPEN", "AI"].join(""), "i"));
});

test("verification form creates a real authenticated API run", async () => {
  const form = await read("../components/app/verify-form.tsx");

  assert.match(form, /authenticatedApiFetch\(user, "\/v1\/verifications"/);
  assert.match(form, /created\.run_id/);
  assert.doesNotMatch(form, /mockedRunId/);
});
