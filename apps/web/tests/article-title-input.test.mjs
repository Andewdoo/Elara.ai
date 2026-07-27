import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const verifyFormPath = new URL("../components/app/verify-form.tsx", import.meta.url);

test("verification submits every request as a claim", async () => {
  const source = await readFile(verifyFormPath, "utf8");

  assert.match(source, /input_type: "CLAIM"/);
  assert.match(source, /text: values\.target/);
  assert.doesNotMatch(source, /ARTICLE_TITLE|article_title|Article URL/);
});

test("verification form exposes only claim input", async () => {
  const source = await readFile(verifyFormPath, "utf8");

  assert.match(source, /Enter a claim\./);
  assert.match(source, />\s*Claim\s*</);
  assert.doesNotMatch(source, /Input type|inputType|RESEARCH|QUOTE|ARTICLE_TEXT|PARAPHRASE|Pasted article|Paraphrase/);
  assert.doesNotMatch(source, /FastAPI performs final validation and durably queues the verification/);
});
