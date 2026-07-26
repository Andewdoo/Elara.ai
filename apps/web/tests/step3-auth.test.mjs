import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Firebase web auth exchanges tokens in headers and never in URLs", async () => {
  const auth = await read("../lib/auth.ts");

  assert.match(auth, /Authorization.*Bearer/);
  assert.match(auth, /createUserWithEmailAndPassword/);
  assert.match(auth, /export async function signUpWithEmail/);
  assert.match(auth, /credentials: "include"/);
  assert.match(auth, /Array\.isArray\(body\?\.detail\)/);
  assert.match(auth, /if \(!response\.ok\)/);
  assert.doesNotMatch(auth, /[?&](token|id_token|session)=/i);
  assert.doesNotMatch(auth, /FIREBASE_(CLIENT_EMAIL|PRIVATE_KEY)/);
  assert.doesNotMatch(auth, new RegExp(["OPEN", "AI"].join(""), "i"));
});

test("auth controls expose email account creation", async () => {
  const controls = await read("../components/app/auth-controls.tsx");
  const provider = await read("../components/providers/firebase-auth-provider.tsx");

  assert.match(controls, /Need an account\? Sign up/);
  assert.match(controls, /Create account/);
  assert.match(controls, /signUpWithEmail/);
  assert.match(provider, /signUpWithEmail/);
});

test("auth provider never leaves the sign-in state pending indefinitely", async () => {
  const provider = await read("../components/providers/firebase-auth-provider.tsx");

  assert.match(provider, /const AUTH_STATE_TIMEOUT_MS = 5_000;/);
  assert.match(provider, /window\.setTimeout\(\(\) => \{\s*complete\(null\);\s*\}, AUTH_STATE_TIMEOUT_MS\)/);
  assert.match(provider, /onAuthStateChanged\(auth, complete, \(\) => \{\s*complete\(null\);\s*\}\)/);
  assert.match(provider, /window\.clearTimeout\(timeout\)/);
});

test("auth controls keep sign-in available while Firebase restores a session", async () => {
  const controls = await read("../components/app/auth-controls.tsx");

  assert.match(controls, /if \(!configured\) \{/);
  assert.doesNotMatch(controls, /!configured \|\| loading|Checking sign-in/);
  assert.match(controls, /Sign in/);
});

test("verification form creates a real authenticated API run", async () => {
  const form = await read("../components/app/verify-form.tsx");

  assert.match(form, /authenticatedApiFetch\(user, "\/v1\/verifications"/);
  assert.match(form, /created\.run_id/);
  assert.doesNotMatch(form, /mockedRunId/);
});
