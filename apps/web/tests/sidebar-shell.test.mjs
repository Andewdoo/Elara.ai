import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:)/, "$1");
const read = (...parts) => readFile(join(root, ...parts), "utf8");

test("full workspace routes retain the accessible sidebar navigation", async () => {
  const shell = await read("components", "app", "app-shell.tsx");

  assert.match(shell, /const \[sidebarOpen, setSidebarOpen\] = useState\(true\)/);
  assert.match(shell, /href="#main-content"/);
  assert.match(shell, /Asterisk/);
  assert.match(shell, /font-editorial/);
  assert.match(shell, /<main id="main-content"/);
  assert.match(shell, /id="primary-sidebar"/);
  assert.match(shell, /aria-label="Workspace navigation"/);
  assert.match(shell, /PanelLeftClose/);
  assert.match(shell, /PanelLeftOpen/);
  assert.doesNotMatch(shell, /Evidence, clearly/);
});

test("full verification form exposes research depth cards and an editorial title", async () => {
  const form = await read("components", "app", "verify-form.tsx");

  assert.match(form, /Start a full verification/);
  assert.match(form, /researchDepthOptions/);
  assert.match(form, /type="radio"/);
  assert.match(form, /font-editorial/);
  assert.match(form, /font-normal/);
  assert.doesNotMatch(form, /Authenticated &amp; secure|server-authoritative systems/);
  assert.match(form, /maxLength=\{12000\}/);
  assert.match(form, /researchDepth === value/);
});

test("signed-in accounts use an avatar menu that reveals sign out", async () => {
  const controls = await read("components", "app", "auth-controls.tsx");

  assert.match(controls, /Account menu for/);
  assert.match(controls, /rounded-full/);
  assert.match(controls, /aria-label="Account options"/);
  assert.match(controls, />\s*Sign out\s*</);
});
