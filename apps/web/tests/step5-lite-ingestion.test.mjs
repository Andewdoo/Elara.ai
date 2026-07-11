import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, "tests", ".tmp", `lite-step5-${process.pid}`);

async function compileLiteModules() {
  const ts = require("typescript");
  const files = ["schemas.ts", "server-config.ts", "deepseek.ts", "supabase.ts", "ingestion.ts"];
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
    ingestion: require(join(moduleDir, "ingestion.js")),
  };
}

const modules = compileLiteModules();

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite ingestion chunks structured records by headings, rows, transcript turns, and semantic breaks", async () => {
  const { ingestion } = await modules;
  const fixture = {
    corpus_version: "lite-corpus-v1",
    documents: [
      {
        id: "demo-doc",
        title: "Demo Source",
        publisher: "Example Publisher",
        document_date: "2025-01-02",
        visibility: "public",
        blocks: [
          { type: "heading", level: 2, text: "First section" },
          {
            type: "paragraph",
            text: "The adopted amount was $12.4 million in fiscal year 2025.",
            page_number: 2,
            paragraph_index: 0,
          },
          { type: "table_row", caption: "Amounts", cells: { Year: "2025", Amount: "$12.4 million" } },
          { type: "semantic_break" },
          { type: "heading", level: 2, text: "Meeting quote" },
          {
            type: "transcript_turn",
            speaker: "Chair Rivera",
            timestamp: "00:01:00",
            text: "The pilot will serve three clinics.",
          },
        ],
      },
    ],
  };

  const corpus = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "fixture",
    now: new Date("2026-07-07T12:00:00.000Z"),
  });
  const chunks = corpus.documents[0].chunks;

  assert.equal(corpus.embedding.mode, "fixture");
  assert.equal(chunks.length, 2);
  assert.deepEqual(chunks[0].heading_path, ["First section"]);
  assert.match(chunks[0].chunk_text, /\$12\.4 million/);
  assert.match(chunks[0].chunk_text, /Year: 2025/);
  assert.deepEqual(chunks[1].heading_path, ["Meeting quote"]);
  assert.match(chunks[1].chunk_text, /Chair Rivera/);
  assert.equal(chunks[0].embedding.length, 1536);
  assert.equal(chunks[0].metadata.overlap_char_count, 0);
});

test("Lite fixture embeddings and content hashes are deterministic", async () => {
  const { ingestion } = await modules;
  const fixture = {
    corpus_version: "lite-corpus-v1",
    documents: [
      {
        id: "hash-demo",
        title: "Hash Demo",
        visibility: "public",
        content_markdown: "# Hash Demo\n\n## Section\n\nA stable paragraph supports reproducible ingestion.",
      },
    ],
  };

  const first = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "fixture",
    now: new Date("2026-07-07T12:00:00.000Z"),
  });
  const second = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "fixture",
    now: new Date("2026-07-07T12:00:00.000Z"),
  });

  assert.equal(first.documents[0].source_content_hash, second.documents[0].source_content_hash);
  assert.equal(first.documents[0].chunks[0].content_hash, second.documents[0].chunks[0].content_hash);
  assert.deepEqual(first.documents[0].chunks[0].embedding.slice(0, 8), second.documents[0].chunks[0].embedding.slice(0, 8));
});

test("Lite ingestion accepts local Markdown source records", async () => {
  const { ingestion } = await modules;
  const markdownPath = join(tempRoot, "source-record.md");
  await mkdir(tempRoot, { recursive: true });
  await writeFile(
    markdownPath,
    "# Markdown Demo\n\n## Quote support\n\nSpeaker Lee: The archived plan covers quote handling only.\n\n| Case | Outcome |\n| --- | --- |\n| Paraphrase | Supported by stored source |\n",
    "utf8",
  );

  const fixture = await ingestion.loadLiteCorpusFixture(markdownPath);
  const corpus = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "fixture",
    now: new Date("2026-07-07T12:00:00.000Z"),
  });

  assert.equal(fixture.documents[0].title, "Markdown Demo");
  assert.match(corpus.documents[0].chunks[0].chunk_text, /Speaker Lee/);
  assert.match(corpus.documents[0].chunks[0].chunk_text, /Paraphrase/);
});

test("Lite ingestion uses DeepSeek-compatible embeddings when configured", async () => {
  const { ingestion } = await modules;
  const calls = [];
  const deepseekClient = {
    embeddingAvailable: true,
    async generateEmbeddings(texts) {
      calls.push(texts);
      return {
        vectors: texts.map(() => Array.from({ length: 1536 }, (_, index) => (index === 0 ? 1 : 0))),
        metadata: {
          provider: "deepseek",
          model: "deepseek-embedding-test",
          prompt_version: "lite-embedding-v1",
          temperature: 0,
          latency_ms: 1,
          token_usage: { input_tokens: 1, output_tokens: 0, total_tokens: 1 },
          generated_at: "2026-07-07T12:00:00.000Z",
        },
      };
    },
  };
  const fixture = {
    corpus_version: "lite-corpus-v1",
    documents: [
      {
        id: "deepseek-demo",
        title: "DeepSeek Demo",
        visibility: "public",
        content_markdown: "# DeepSeek Demo\n\n## Section\n\nA chunk needs an approved embedding route.",
      },
    ],
  };

  const corpus = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "auto",
    deepseekClient,
    now: new Date("2026-07-07T12:00:00.000Z"),
  });

  assert.equal(corpus.embedding.mode, "deepseek");
  assert.equal(corpus.embedding.model, "deepseek-embedding-test");
  assert.equal(calls.length, 1);
  assert.equal(corpus.documents[0].chunks[0].embedding[0], 1);
});

test("Lite Supabase ingestion writes only through service-role server requests", async () => {
  const { ingestion } = await modules;
  const requests = [];
  const fixture = {
    corpus_version: "lite-corpus-v1",
    documents: [
      {
        id: "write-demo",
        title: "Write Demo",
        visibility: "public",
        content_markdown: "# Write Demo\n\n## Section\n\nThis source is inserted only through the server utility.",
      },
    ],
  };
  const corpus = await ingestion.prepareLiteCorpus(fixture, {
    embeddingMode: "fixture",
    now: new Date("2026-07-07T12:00:00.000Z"),
  });

  const result = await ingestion.ingestLiteCorpusToSupabase(corpus, {
    config: {
      url: "https://supabase.example.test",
      serviceRoleKey: "sb_secret_server_only",
      schema: "public",
    },
    fetchImpl: async (url, init) => {
      requests.push({ url, init });
      if (String(url).includes("lite_documents")) {
        return new Response(JSON.stringify([{ id: "00000000-0000-0000-0000-000000000001" }]), {
          status: 201,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(null, { status: 204 });
    },
  });

  assert.equal(result.dry_run, false);
  assert.equal(result.document_count, 1);
  assert.equal(result.chunk_count, 1);
  assert.equal(requests.length, 3);
  for (const request of requests) {
    assert.equal(request.init.headers.Authorization, undefined);
    assert.equal(request.init.headers.apikey, "sb_secret_server_only");
    assert.equal(request.init.headers["Content-Profile"], "public");
  }
  assert.match(requests[0].url, /on_conflict=corpus_version,source_content_hash/);
  assert.equal(requests[1].init.method, "DELETE");
  assert.equal(requests[2].init.method, "POST");
  assert.doesNotMatch(JSON.stringify(requests), new RegExp("Open" + "AI", "i"));
});
