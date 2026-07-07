import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, "tests", ".tmp", `lite-step4-${process.pid}`);

async function compileLiteModules() {
  const ts = require("typescript");
  const files = ["schemas.ts", "server-config.ts", "supabase.ts", "deepseek.ts"];
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
    deepseek: require(join(moduleDir, "deepseek.js")),
    supabase: require(join(moduleDir, "supabase.js")),
  };
}

const modules = compileLiteModules();

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite server credentials fail closed when production-like Supabase config is missing", async () => {
  const { supabase } = await modules;

  assert.throws(
    () => supabase.loadLiteSupabaseConfig({ NODE_ENV: "production", LITE_DEMO_ENABLED: "true" }),
    (error) =>
      error?.name === "LiteServerConfigurationError" &&
      error.missing.includes("SUPABASE_URL") &&
      error.missing.includes("SUPABASE_SERVICE_ROLE_KEY"),
  );
});

test("Lite DeepSeek env validation requires only server-side DEEPSEEK names", async () => {
  const { deepseek } = await modules;

  assert.throws(
    () => deepseek.loadLiteDeepSeekConfig({ NODE_ENV: "production", LITE_DEMO_ENABLED: "true" }),
    (error) =>
      error?.name === "LiteDeepSeekConfigurationError" &&
      error.missing.includes("DEEPSEEK_API_KEY") &&
      error.missing.includes("DEEPSEEK_BASE_URL") &&
      !error.missing.includes("DEEPSEEK_EMBEDDING_MODEL"),
  );
});

test("Lite DeepSeek structured JSON calls use low temperature, metadata, and mocked fetch", async () => {
  const { deepseek } = await modules;
  const z = require("zod");
  const captured = {};

  const client = new deepseek.DeepSeekClient({
    config: {
      apiKey: "server-secret",
      baseUrl: "https://deepseek.example.test",
      chatModel: "deepseek-chat-test",
      reasoningModel: "deepseek-reasoner-test",
    },
    fetchImpl: async (url, init) => {
      captured.url = url;
      captured.headers = init.headers;
      captured.body = JSON.parse(init.body);
      return new Response(
        JSON.stringify({
          id: "resp-123",
          model: "deepseek-chat-test",
          choices: [{ message: { content: "```json\n{\"answer\":\"grounded\"}\n```" }, finish_reason: "stop" }],
          usage: { prompt_tokens: 11, completion_tokens: 3, total_tokens: 14 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
    logger: { info() {}, warn() {} },
  });

  const result = await client.generateStructured({
    messages: [{ role: "user", content: "private evidence text" }],
    outputSchema: z.object({ answer: z.string() }),
    promptVersion: "lite-synthesis-v1",
    temperature: 0,
  });

  assert.equal(result.output.answer, "grounded");
  assert.equal(result.metadata.provider, "deepseek");
  assert.equal(result.metadata.prompt_version, "lite-synthesis-v1");
  assert.equal(result.metadata.token_usage.total_tokens, 14);
  assert.equal(captured.url, "https://deepseek.example.test/chat/completions");
  assert.equal(captured.body.temperature, 0);
  assert.deepEqual(captured.body.response_format, { type: "json_object" });
  assert.equal(captured.body.stream, false);
  assert.match(captured.headers.Authorization, /^Bearer server-secret$/);
  assert.doesNotMatch(JSON.stringify(captured.body), new RegExp("Open" + "AI", "i"));
});

test("Lite DeepSeek maps provider errors without logging prompts, bodies, or secrets", async () => {
  const { deepseek } = await modules;
  const z = require("zod");
  const logs = [];

  const client = new deepseek.DeepSeekClient({
    config: {
      apiKey: "server-secret",
      baseUrl: "https://deepseek.example.test",
      chatModel: "deepseek-chat-test",
      reasoningModel: "deepseek-reasoner-test",
    },
    fetchImpl: async () =>
      new Response(JSON.stringify({ error: { message: "provider-private-body" } }), {
        status: 503,
        headers: { "content-type": "application/json" },
      }),
    logger: { info() {}, warn(message, metadata) { logs.push({ message, metadata }); } },
  });

  await assert.rejects(
    () =>
      client.generateStructured({
        messages: [{ role: "user", content: "DO-NOT-LOG-SOURCE" }],
        outputSchema: z.object({ answer: z.string() }),
        promptVersion: "lite-audit-v1",
      }),
    (error) => error?.code === "deepseek_unavailable" && error.retryable === true,
  );

  const logText = JSON.stringify(logs);
  assert.doesNotMatch(logText, /DO-NOT-LOG-SOURCE/);
  assert.doesNotMatch(logText, /provider-private-body/);
  assert.doesNotMatch(logText, /server-secret/);
});

test("Lite embedding route absence exposes a named lexical metadata fallback", async () => {
  const { deepseek } = await modules;
  const client = new deepseek.DeepSeekClient({
    config: {
      apiKey: "server-secret",
      baseUrl: "https://deepseek.example.test",
      chatModel: "deepseek-chat-test",
      reasoningModel: "deepseek-reasoner-test",
    },
    fetchImpl: async () => {
      throw new Error("fetch should not be called without an embedding model");
    },
    logger: { info() {}, warn() {} },
  });

  assert.equal(client.embeddingAvailable, false);
  await assert.rejects(() => client.generateEmbeddings(["policy effective 2024"]), {
    name: "LiteDeepSeekEmbeddingUnavailableError",
    code: "deepseek_embedding_route_unavailable",
  });

  const fallback = client.createLexicalMetadataFallback("The policy took effect in March 2024.");
  assert.equal(fallback.kind, "lexical_metadata_fallback");
  assert.equal(fallback.vectors, null);
  assert.deepEqual(fallback.lexical_terms.slice(0, 3), ["policy", "took", "effect"]);
});

test("Lite Supabase helper uses service-role headers only in mocked server client", async () => {
  const { supabase } = await modules;
  const captured = {};
  const reviewedAt = "2026-07-07T12:00:00.000Z";

  const client = new supabase.LiteSupabaseClient({
    config: {
      url: "https://supabase.example.test",
      serviceRoleKey: "service-role-secret",
      schema: "public",
    },
    fetchImpl: async (url, init) => {
      captured.url = url;
      captured.headers = init.headers;
      captured.body = JSON.parse(init.body);
      return new Response(
        JSON.stringify([
          {
            chunk_id: "chunk-1",
            document_id: "doc-1",
            title: "Demo Source",
            source_url: "https://example.com/source",
            publisher: "Example",
            document_date: "2024-03-01",
            corpus_version: "lite-corpus-v1",
            chunk_text: "The policy took effect on March 1, 2024.",
            heading_path: ["Implementation", "Effective date"],
            page_number: 2,
            section_label: "Section 2",
            paragraph_index: 1,
            content_hash: "hash-123456",
            source_citation_label: "Demo Source, section 2",
            similarity: 0.82,
          },
        ]),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
    logger: { info() {}, warn() {} },
  });

  const chunks = await client.matchLiteChunks({
    queryEmbedding: [0.1, 0.2, 0.3],
    corpusVersion: "lite-corpus-v1",
    matchCount: 3,
    reviewedAt,
  });

  assert.equal(captured.url, "https://supabase.example.test/rest/v1/rpc/match_lite_chunks");
  assert.equal(captured.headers.Authorization, "Bearer service-role-secret");
  assert.equal(captured.headers.apikey, "service-role-secret");
  assert.equal(captured.headers["Content-Profile"], "public");
  assert.equal(captured.body.filter_corpus_version, "lite-corpus-v1");
  assert.equal(chunks[0].chunk_id, "chunk-1");
  assert.equal(chunks[0].reviewed_at, reviewedAt);
  assert.equal(chunks[0].retrieval_scores.semantic, 0.82);
});
