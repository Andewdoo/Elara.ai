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

test("standard verification form exposes only claim, article-title, and quote modes", async () => {
  const source = await readFile(verifyFormPath, "utf8");

  assert.match(source, /z\.enum\(\["CLAIM", "ARTICLE_TITLE", "QUOTE"\]\)/);
  assert.doesNotMatch(source, /ARTICLE_TEXT|PARAPHRASE|Pasted article|Paraphrase/);
  assert.doesNotMatch(source, /FastAPI performs final validation and durably queues the verification/);
});
