import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
test("Sentry is scoped to the web workspace without replay or PII", () => {
  const client = read("instrumentation-client.ts");
  const server = read("sentry.server.config.ts");
  const edge = read("sentry.edge.config.ts");
  const config = read("next.config.mjs");
  assert.match(client, /NEXT_PUBLIC_SENTRY_DSN/);
  assert.match(client, /sendDefaultPii:\s*false/);
  assert.doesNotMatch(client, /replayIntegration/);
  assert.match(server, /delete event\.request\.data/);
  assert.match(edge, /delete event\.request\.data/);
  assert.match(config, /SENTRY_PROJECT_WEB/);
  assert.match(config, /SENTRY_AUTH_TOKEN/);
});
