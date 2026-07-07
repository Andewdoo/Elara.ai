import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, "tests", ".tmp", `lite-step6-${process.pid}`);

async function compileLiteModules() {
  const ts = require("typescript");
  const files = ["schemas.ts", "server-config.ts", "deepseek.ts", "supabase.ts", "retrieval.ts"];
  const moduleDir = join(tempRoot, "lib", "lite");
  await mkdir(moduleDir, { recursive: true });
  await writeFile(join(tempRoot, "package.json"), "{\"type\":\"commonjs\"}", "utf8");

  for (const file of files) {
    const sourcePath = join(root, "lib", "lite", file);
    const source = await readFile(sourcePath, "utf8");
    const output = ts.transpileModule(source, {
      fileName: sourcePath,
      reportDiagnostics: true,
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    });
    const errors = output.diagnostics?.filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error) ?? [];
    assert.equal(errors.length, 0, `${file} should transpile without TypeScript diagnostics`);
    await writeFile(join(moduleDir, file.replace(/\.ts$/, ".js")), output.outputText, "utf8");
  }

  return {
    retrieval: require(join(moduleDir, "retrieval.js")),
  };
}

const modules = compileLiteModules();
const reviewedAt = "2026-07-07T12:00:00.000Z";

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite vector retrieval embeds when available and preserves metadata", async () => {
  const { retrieval } = await modules;
  const calls = { embeddings: [], vector: [], lexical: [] };
  const chunks = await retrieval.retrieveLiteChunks({
    request: request("Did Ada Lovelace quote \"poetical science\" in 1843?"),
    queryPlan: {
      embedding_text: "Ada Lovelace poetical science 1843",
      lexical_terms: ["ada", "lovelace", "poetical", "science", "1843"],
      query_variants: ["Ada Lovelace poetical science quote"],
      entity_filters: { person: "Ada Lovelace" },
    },
    reviewedAt,
    deepseekClient: {
      embeddingAvailable: true,
      async generateEmbeddings(texts) {
        calls.embeddings.push(texts);
        return { vectors: [[0.1, 0.2, 0.3]], metadata: {} };
      },
      createLexicalMetadataFallback() {
        throw new Error("fallback should not run");
      },
    },
    supabaseClient: {
      async matchLiteChunks(vectorRequest) {
        calls.vector.push(vectorRequest);
        return [chunk("chunk-vector", "Ada Lovelace called the Analytical Engine a form of poetical science in 1843.", {
          semantic: 0.74,
          metadata: { archivist_note: "curated" },
        })];
      },
      async searchLiteChunks(lexicalRequest) {
        calls.lexical.push(lexicalRequest);
        return [];
      },
    },
  });

  assert.equal(calls.embeddings.length, 1);
  assert.deepEqual(calls.vector[0].queryEmbedding, [0.1, 0.2, 0.3]);
  assert.equal(calls.vector[0].corpusVersion, "lite-corpus-v1");
  assert.equal(calls.vector[0].includePrivate, false);
  assert.equal(calls.lexical.length, 1);
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].chunk_id, "chunk-vector");
  assert.equal(chunks[0].metadata.archivist_note, "curated");
  assert.equal(chunks[0].metadata.low_confidence_retrieval, false);
  assert.equal(chunks[0].retrieval_scores.low_confidence, false);
  assert.match(chunks[0].chunk_text, /poetical science/);
});

test("Lite lexical fallback runs when embeddings are unavailable", async () => {
  const { retrieval } = await modules;
  const calls = { fallback: [], vector: 0, lexical: [] };
  const chunks = await retrieval.retrieveLiteChunks({
    request: request("Which source mentions three clinics?"),
    reviewedAt,
    deepseekClient: {
      embeddingAvailable: false,
      async generateEmbeddings() {
        throw new Error("embedding should not run");
      },
      createLexicalMetadataFallback(queryStrings) {
        calls.fallback.push(queryStrings);
        return { kind: "lexical_metadata_fallback" };
      },
    },
    supabaseClient: {
      async matchLiteChunks() {
        calls.vector += 1;
        return [];
      },
      async searchLiteChunks(lexicalRequest) {
        calls.lexical.push(lexicalRequest);
        return [chunk("chunk-lexical", "The pilot will serve three clinics during the public demo.")];
      },
    },
  });

  assert.equal(calls.vector, 0);
  assert.equal(calls.fallback.length, 1);
  assert.match(calls.lexical[0].queryStrings.join(" "), /three clinics/i);
  assert.equal(chunks[0].chunk_id, "chunk-lexical");
  assert.ok(chunks[0].retrieval_scores.lexical > 0);
});

test("Lite exact quote and number matching boosts deterministic ranking", async () => {
  const { retrieval } = await modules;
  const chunks = await retrieval.retrieveLiteChunks({
    request: request("Did the memo say \"serve three clinics\" and cite 2025?"),
    reviewedAt,
    deepseekClient: noEmbeddingClient(),
    supabaseClient: {
      async matchLiteChunks() {
        return [];
      },
      async searchLiteChunks() {
        return [
          chunk("chunk-background", "The memo discusses clinics and service levels in general for 2025."),
          chunk("chunk-exact", "The approved memo states the pilot will serve three clinics in 2025."),
        ];
      },
    },
  });

  assert.equal(chunks[0].chunk_id, "chunk-exact");
  assert.ok(chunks[0].retrieval_scores.combined > chunks[1].retrieval_scores.combined);
  assert.deepEqual(chunks[0].metadata.matched_exact_signals.quotes, ["serve three clinics"]);
  assert.deepEqual(chunks[0].metadata.matched_exact_signals.numbers, ["2025"]);
});

test("Lite retrieval applies corpus and visibility filters to Supabase requests", async () => {
  const { retrieval } = await modules;
  const calls = [];
  await retrieval.retrieveLiteChunks({
    request: request("Find the public pilot memo."),
    filters: {
      corpusVersion: "lite-corpus-v1",
      publisher: "Example Publisher",
      documentDateStart: "2025-01-01",
      documentDateEnd: "2025-12-31",
      includePrivate: false,
    },
    reviewedAt,
    deepseekClient: noEmbeddingClient(),
    supabaseClient: {
      async matchLiteChunks() {
        return [];
      },
      async searchLiteChunks(lexicalRequest) {
        calls.push(lexicalRequest);
        return [];
      },
    },
  });

  assert.equal(calls[0].corpusVersion, "lite-corpus-v1");
  assert.equal(calls[0].publisher, "Example Publisher");
  assert.equal(calls[0].documentDateStart, "2025-01-01");
  assert.equal(calls[0].documentDateEnd, "2025-12-31");
  assert.equal(calls[0].includePrivate, false);
});

test("Lite retrieval returns an empty bounded set without deciding truth", async () => {
  const { retrieval } = await modules;
  const chunks = await retrieval.retrieveLiteChunks({
    request: request("Does the library cover a missing topic?"),
    reviewedAt,
    deepseekClient: noEmbeddingClient(),
    supabaseClient: {
      async matchLiteChunks() {
        return [];
      },
      async searchLiteChunks() {
        return [];
      },
    },
  });

  assert.deepEqual(chunks, []);
});

test("Lite retrieval deduplicates near-identical chunks and marks low confidence", async () => {
  const { retrieval } = await modules;
  const chunks = await retrieval.retrieveLiteChunks({
    request: request("Find beta deployment claim."),
    reviewedAt,
    deepseekClient: noEmbeddingClient(),
    supabaseClient: {
      async matchLiteChunks() {
        return [];
      },
      async searchLiteChunks() {
        return [
          chunk("chunk-dup-1", "Alpha beta deployment details remain background only.", { content_hash: "hash-dup-a" }),
          chunk("chunk-dup-2", "Alpha beta deployment details remain background only.", { content_hash: "hash-dup-b" }),
          chunk("chunk-weak", "Unrelated archive table of contents.", { content_hash: "hash-weak" }),
        ];
      },
    },
  });

  assert.equal(chunks.filter((candidate) => candidate.chunk_text.includes("Alpha beta")).length, 1);
  assert.equal(chunks.find((candidate) => candidate.chunk_id === "chunk-weak")?.retrieval_scores.low_confidence, true);
  assert.equal(chunks.find((candidate) => candidate.chunk_id === "chunk-weak")?.metadata.low_confidence_retrieval, true);
});

function request(input) {
  return { corpus_version: "lite-corpus-v1", input };
}

function noEmbeddingClient() {
  return {
    embeddingAvailable: false,
    async generateEmbeddings() {
      throw new Error("embedding should not run");
    },
    createLexicalMetadataFallback() {
      return { kind: "lexical_metadata_fallback" };
    },
  };
}

function chunk(id, text, options = {}) {
  return {
    corpus_version: "lite-corpus-v1",
    chunk_id: id,
    document_id: options.document_id ?? "doc-1",
    source_label: options.source_label ?? "Demo Source, section 1",
    source_title: options.source_title ?? "Demo Source",
    source_url: "https://example.com/demo-source",
    publisher: options.publisher ?? "Example Publisher",
    document_date: options.document_date ?? "2025-01-02",
    reviewed_at: reviewedAt,
    chunk_text: text,
    heading_path: "Section 1",
    page_or_position: "section 1",
    paragraph_index: 0,
    content_hash: options.content_hash ?? `hash-${id}`,
    retrieval_scores: {
      semantic: options.semantic,
      lexical: 0,
      metadata: 0,
      combined: options.semantic ?? 0,
    },
    retrieval_strategy: {
      name: "hybrid_pgvector_lexical",
      version: "test",
      semantic_top_k: 8,
      lexical_top_k: 8,
      final_top_k: 8,
      min_similarity: 0.35,
      filters: { corpus_version: "lite-corpus-v1" },
    },
    metadata: options.metadata ?? {},
  };
}
