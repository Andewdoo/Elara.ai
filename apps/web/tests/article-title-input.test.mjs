import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const verifyFormPath = new URL("../components/app/verify-form.tsx", import.meta.url);

test("article-title mode submits a title for Brave discovery instead of an article URL", async () => {
  const source = await readFile(verifyFormPath, "utf8");

  assert.match(source, /ARTICLE_TITLE/);
  assert.match(source, /article_title: values\.target/);
  assert.match(source, /Elara searches Brave for this title/);
  assert.doesNotMatch(source, /Article URL/);
});

test("standard verification form exposes claim and article-title modes plus disabled upcoming research", async () => {
  const source = await readFile(verifyFormPath, "utf8");

  assert.match(source, /z\.enum\(\["CLAIM", "ARTICLE_TITLE"\]\)/);
  assert.match(source, /<option value="RESEARCH" disabled>/);
  assert.match(source, /Research — Coming soon/);
  assert.doesNotMatch(source, /QUOTE|ARTICLE_TEXT|PARAPHRASE|Pasted article|Paraphrase/);
  assert.doesNotMatch(source, /FastAPI performs final validation and durably queues the verification/);
});
