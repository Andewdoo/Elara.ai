import assert from "node:assert/strict";
import { mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, extname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = join(root, "..", "..");
const tempRoot = join(root, "tests", ".tmp", `lite-step12-${process.pid}`);
const reviewedAt = "2026-07-07T12:00:00.000Z";
const corpusVersion = "lite-corpus-v1";

async function compileLiteModules() {
  const ts = require("typescript");
  const files = [
    "schemas.ts",
    "server-config.ts",
    "deepseek.ts",
    "supabase.ts",
    "retrieval.ts",
    "prompt-utils.ts",
    "prompts/intake.ts",
    "prompts/query-planner.ts",
    "prompts/evidence-judge.ts",
    "prompts/synthesis.ts",
    "prompts/citation-audit.ts",
    "pipeline.ts",
  ];
  const moduleDir = join(tempRoot, "lib", "lite");
  await mkdir(moduleDir, { recursive: true });
  await writeFile(join(tempRoot, "package.json"), "{\"type\":\"commonjs\"}", "utf8");

  for (const file of files) {
    await transpile(ts, join(root, "lib", "lite", file), join(moduleDir, file.replace(/\.ts$/, ".js")));
  }

  return {
    pipeline: require(join(moduleDir, "pipeline.js")),
    moduleDir,
  };
}

async function compileRouteModule() {
  const ts = require("typescript");
  await mkdir(join(tempRoot, "route", "app", "api", "lite", "answer"), { recursive: true });
  await mkdir(join(tempRoot, "route", "lib", "lite"), { recursive: true });
  await mkdir(join(tempRoot, "route", "fakes"), { recursive: true });
  await writeFile(join(tempRoot, "route", "package.json"), "{\"type\":\"commonjs\"}", "utf8");
  await writeFile(
    join(tempRoot, "route", "fakes", "pipeline.js"),
    "exports.answerLiteClaim = async () => { throw new Error('inject pipeline'); };\n",
    "utf8",
  );
  await writeFile(
    join(tempRoot, "route", "fakes", "run-persistence.js"),
    "exports.persistLiteRunIfConfigured = async () => 'skipped';\n",
    "utf8",
  );

  for (const file of ["schemas.ts", "server-config.ts"]) {
    await transpile(
      ts,
      join(root, "lib", "lite", file),
      join(tempRoot, "route", "lib", "lite", file.replace(/\.ts$/, ".js")),
    );
  }

  const routeSource = (await readFile(join(root, "app", "api", "lite", "answer", "route.ts"), "utf8"))
    .replace("@/lib/lite/pipeline", "../../../../fakes/pipeline.js")
    .replace("@/lib/lite/run-persistence", "../../../../fakes/run-persistence.js")
    .replace("@/lib/lite/schemas", "../../../../lib/lite/schemas.js");
  await transpileSource(
    ts,
    routeSource,
    join(root, "app", "api", "lite", "answer", "route.ts"),
    join(tempRoot, "route", "app", "api", "lite", "answer", "route.js"),
  );

  return require(join(tempRoot, "route", "app", "api", "lite", "answer", "route.js"));
}

async function transpile(ts, sourcePath, outputPath) {
  const source = await readFile(sourcePath, "utf8");
  await transpileSource(ts, source, sourcePath, outputPath);
}

async function transpileSource(ts, source, sourcePath, outputPath) {
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
  assert.equal(errors.length, 0, `${sourcePath} should transpile without TypeScript diagnostics`);
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output.outputText, "utf8");
}

const liteModules = compileLiteModules();
const routeModule = compileRouteModule();

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite browser code never imports server-only clients or private credential names", async () => {
  const clientFiles = await findClientFiles([join(root, "app"), join(root, "components"), join(root, "lib")]);
  assert.ok(clientFiles.length > 0, "expected browser-facing files to scan");

  const serverOnlyImports = [
    "@/lib/lite/deepseek",
    "@/lib/lite/supabase",
    "@/lib/lite/server-config",
    "@/lib/lite/pipeline",
    "@/lib/lite/retrieval",
    "@/lib/lite/run-persistence",
  ];
  const privateCredentialNames = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_CHAT_MODEL",
    "DEEPSEEK_REASONING_MODEL",
    "DEEPSEEK_EMBEDDING_MODEL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_URL",
  ];

  for (const file of clientFiles) {
    const source = await readFile(file, "utf8");
    for (const importPath of serverOnlyImports) {
      assert.doesNotMatch(source, new RegExp(escapeRegExp(importPath)), `${rel(file)} imports ${importPath}`);
    }
    for (const credentialName of privateCredentialNames) {
      assert.doesNotMatch(source, new RegExp(credentialName), `${rel(file)} references ${credentialName}`);
    }
  }

  const envExample = await readFile(join(repoRoot, ".env.example"), "utf8");
  assert.doesNotMatch(envExample, /NEXT_PUBLIC_DEEPSEEK_/);
  assert.doesNotMatch(envExample, /NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_KEY/);
});

test("Lite server-only modules fail closed in a browser-like runtime", async () => {
  const { moduleDir } = await liteModules;
  const serverOnlyModules = ["deepseek.js", "supabase.js", "retrieval.js", "pipeline.js"];
  const previousWindow = globalThis.window;

  for (const file of serverOnlyModules) {
    const modulePath = join(moduleDir, file);
    delete require.cache[require.resolve(modulePath)];
    globalThis.window = {};
    assert.throws(
      () => require(modulePath),
      (error) =>
        error?.name === "LiteServerConfigurationError" &&
        /server-only/i.test(error.message),
      `${file} should reject browser execution`,
    );
    delete require.cache[require.resolve(modulePath)];
  }

  if (previousWindow === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = previousWindow;
  }
});

test("Lite route rejects malformed and overlong input before calling the pipeline", async () => {
  const route = await routeModule;
  let pipelineCalls = 0;
  const dependencies = {
    answerLiteClaim: async () => {
      pipelineCalls += 1;
      return answerResponse("11111111-1111-4111-8111-111111111111");
    },
    persistLiteRunIfConfigured: async () => "skipped",
    rateBuckets: new Map(),
  };

  const malformed = await route.handleLiteAnswerRequest(
    new Request("https://elara.example.test/api/lite/answer", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{not-json",
    }),
    dependencies,
  );
  const tooLongBody = JSON.stringify(validRequest({ input: "A".repeat(7000) }));
  const overlong = await route.handleLiteAnswerRequest(
    new Request("https://elara.example.test/api/lite/answer", {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": String(tooLongBody.length) },
      body: tooLongBody,
    }),
    dependencies,
  );
  const unsupportedContentType = await route.handleLiteAnswerRequest(
    new Request("https://elara.example.test/api/lite/answer", {
      method: "POST",
      headers: { "content-type": "text/plain" },
      body: "not a json request",
    }),
    dependencies,
  );
  const schemaOverlong = await route.handleLiteAnswerRequest(
    new Request("https://elara.example.test/api/lite/answer", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(validRequest({ input: "A".repeat(4001) })),
    }),
    dependencies,
  );

  assert.equal(malformed.status, 400);
  assert.equal((await malformed.json()).error_code, "lite_invalid_json");
  assert.equal(overlong.status, 413);
  assert.equal((await overlong.json()).error_code, "lite_request_too_large");
  assert.equal(schemaOverlong.status, 400);
  assert.equal((await schemaOverlong.json()).error_code, "lite_invalid_request");
  assert.equal(unsupportedContentType.status, 415);
  assert.equal(pipelineCalls, 0);
});

test("Lite pipeline does not publish unsupported answers as supported results", async () => {
  const { pipeline } = await liteModules;
  const response = await pipeline.answerLiteClaim({
    request: validRequest(),
    reviewedAt,
    runId: "lite-test-all-unsupported",
    deepseekClient: fakeClient({
      "lite-evidence-judge-v1": {
        judgments: [
          {
            chunk_id: "chunk-support",
            stance: "supports",
            cited_span: "took effect on March 1, 2024",
            rationale: "The passage states the effective date.",
            confidence: 0.91,
            uncertainty: [],
          },
        ],
      },
      "lite-synthesis-v1": {
        status: "answer",
        answer_markdown: "The rollout covered every state immediately.",
        cited_sentences: [
          {
            sentence_index: 0,
            text: "The rollout covered every state immediately.",
            citation_ids: ["chunk-support"],
            confidence: 0.83,
            uncertainty: [],
          },
        ],
        limitations: [],
        confidence: 0.83,
        uncertainty: [],
      },
      "lite-citation-audit-v1": {
        sentence_support: [
          {
            sentence_index: 0,
            citation_id: "chunk-support",
            support_status: "unsupported",
            reason: "The cited chunk does not mention every state.",
            confidence: 0.94,
          },
        ],
      },
    }),
    retrieveChunks: async () => [chunk("chunk-support", "The policy took effect on March 1, 2024.")],
  });

  assert.equal(response.kind, "insufficient_evidence");
  assert.equal(response.audit_status, "insufficient_evidence");
  assert.equal(response.citation_audit?.audit_status, "rejected");
  assert.match(response.gaps.join(" "), /citation audit removed every factual sentence/i);
});

test("Lite citations must reference selected existing chunks", async () => {
  const { pipeline } = await liteModules;
  const response = await pipeline.answerLiteClaim({
    request: validRequest(),
    reviewedAt,
    runId: "lite-test-unknown-citation",
    deepseekClient: fakeClient({
      "lite-evidence-judge-v1": {
        judgments: [
          {
            chunk_id: "chunk-support",
            stance: "supports",
            cited_span: "took effect on March 1, 2024",
            rationale: "The passage states the effective date.",
            confidence: 0.91,
            uncertainty: [],
          },
        ],
      },
      "lite-synthesis-v1": {
        status: "answer",
        answer_markdown: "The policy took effect on March 1, 2024.",
        cited_sentences: [
          {
            sentence_index: 0,
            text: "The policy took effect on March 1, 2024.",
            citation_ids: ["chunk-not-selected"],
            confidence: 0.9,
            uncertainty: [],
          },
        ],
        limitations: [],
        confidence: 0.9,
        uncertainty: [],
      },
      "lite-citation-audit-v1": () => {
        throw new Error("deterministic unknown-chunk rejection should not call the audit model");
      },
    }),
    retrieveChunks: async () => [chunk("chunk-support", "The policy took effect on March 1, 2024.")],
  });

  assert.equal(response.kind, "insufficient_evidence");
  assert.equal(response.citation_audit?.audit_status, "rejected");
  assert.deepEqual(response.citation_audit?.unknown_chunk_ids, ["chunk-not-selected"]);
  assert.equal(response.citation_audit?.rejected_sentences[0].support_status, "unknown_chunk");
});

test("Lite Supabase policies deny public writes and privileged retrieval to anon/authenticated roles", async () => {
  const sql = await readFile(join(repoRoot, "infrastructure", "lite", "001_supabase_lite_schema.sql"), "utf8");
  const tables = [
    "lite_documents",
    "lite_chunks",
    "lite_runs",
    "lite_run_citations",
    "lite_feedback",
    "lite_eval_cases",
  ];

  for (const table of tables) {
    assert.match(sql, new RegExp(`alter table public\\.${table}\\s+enable row level security`, "i"));
    assert.match(sql, new RegExp(`revoke all on table public\\.${table} from anon, authenticated`, "i"));
    assert.match(sql, new RegExp(`grant all on table public\\.${table} to service_role`, "i"));
    for (const action of ["insert", "update", "delete"]) {
      assert.match(
        sql,
        new RegExp(`create policy ${table}_no_public_${action}[\\s\\S]*?on public\\.${table}[\\s\\S]*?for ${action}[\\s\\S]*?to anon, authenticated[\\s\\S]*?\\(false\\)`, "i"),
        `${table} should deny public ${action}`,
      );
    }
  }

  assert.doesNotMatch(sql, /grant\s+(insert|update|delete|all)\s+on\s+(table\s+)?public\.lite_\w+\s+to\s+(anon|authenticated)/i);
  assert.match(sql, /revoke execute on function public\.match_lite_chunks[\s\S]*from public, anon, authenticated/i);
  assert.match(sql, /grant execute on function public\.match_lite_chunks[\s\S]*to service_role/i);
  assert.doesNotMatch(sql, /grant execute on function public\.match_lite_chunks[\s\S]*to (anon|authenticated)/i);
  assert.match(sql, /grant select on table public\.lite_public_documents to anon, authenticated/i);
});

test("Lite code does not call Full Mode, search, queue, cache, storage, or Firebase Admin services", async () => {
  const files = await listFiles([join(root, "app", "api", "lite"), join(root, "lib", "lite"), join(root, "components", "lite")]);
  const forbiddenPatterns = [
    /\bBrave\b|BRAVE_/i,
    /\bFastAPI\b|\/v1\/verifications|NEXT_PUBLIC_API_BASE_URL/i,
    /\bRedis\b|REDIS_/i,
    /\bCelery\b|CELERY_/i,
    /\bS3\b|S3_|OBJECT_STORAGE_|AWS_ACCESS_KEY|AWS_SECRET|R2_/i,
    /Firebase Admin|firebase-admin|FIREBASE_ADMIN|GOOGLE_APPLICATION_CREDENTIALS/i,
  ];

  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const pattern of forbiddenPatterns) {
      assert.doesNotMatch(source, pattern, `${rel(file)} should stay within the Lite serverless/Supabase/DeepSeek boundary`);
    }
  }
});

function validRequest(overrides = {}) {
  return {
    corpus_version: corpusVersion,
    input: "Did the policy take effect on March 1, 2024?",
    input_type_hint: "question",
    client_trace_id: "trace-step12",
    ...overrides,
  };
}

function answerResponse(id) {
  const retrievalStrategy = retrievalStrategyFixture();
  const citedSentence = {
    sentence_index: 0,
    text: "The curated evidence says the policy took effect on March 1, 2024.",
    citation_ids: ["chunk-support"],
    source_labels: ["Demo Source, section 1"],
    support_status: "supported",
    confidence: 0.9,
    uncertainty: [],
  };
  const chunkFixture = chunk("chunk-support", "The policy took effect on March 1, 2024.");
  const promptVersions = {
    intake: "lite-intake-v1",
    query_planner: "lite-query-planner-v1",
    evidence_judge: "lite-evidence-judge-v1",
    synthesis: "lite-synthesis-v1",
    citation_audit: "lite-citation-audit-v1",
  };

  return {
    kind: "answer",
    status: "answered",
    run_id: id,
    corpus_version: corpusVersion,
    reviewed_at: reviewedAt,
    request: validRequest(),
    retrieval_strategy: retrievalStrategy,
    chunk_ids: ["chunk-support"],
    source_labels: ["Demo Source, section 1"],
    model_metadata: { provider: "deepseek", stages: { synthesis: model("lite-synthesis-v1") } },
    prompt_versions: promptVersions,
    report_metadata: reportMetadata(promptVersions, retrievalStrategy),
    confidence: 0.82,
    uncertainty: [],
    audit_status: "passed",
    selected_context: {
      corpus_version: corpusVersion,
      reviewed_at: reviewedAt,
      retrieval_strategy: retrievalStrategy,
      selected_chunk_ids: ["chunk-support"],
      chunks: [chunkFixture],
      judgments: [],
      context_token_budget: 6000,
      selection_reason: "Fixture.",
      confidence: 0.8,
      uncertainty: [],
    },
    synthesis: {
      prompt_version: "lite-synthesis-v1",
      model: model("lite-synthesis-v1"),
      status: "answer",
      answer_markdown: citedSentence.text,
      cited_sentences: [citedSentence],
      limitations: [],
      confidence: 0.88,
      uncertainty: [],
    },
    citation_audit: {
      prompt_version: "lite-citation-audit-v1",
      model: model("lite-citation-audit-v1"),
      audit_status: "passed",
      checked_sentence_count: 1,
      accepted_sentence_indices: [0],
      rejected_sentences: [],
      missing_citation_sentence_indices: [],
      unknown_chunk_ids: [],
      confidence: 0.92,
      uncertainty: [],
    },
    answer_markdown: citedSentence.text,
    cited_sentences: [citedSentence],
  };
}

function fakeClient(overrides = {}) {
  return {
    embeddingAvailable: false,
    async generateEmbeddings() {
      throw new Error("embeddings should not run in Step 12 tests");
    },
    createLexicalMetadataFallback() {
      return { kind: "lexical_metadata_fallback" };
    },
    async generateStructured(request) {
      const override = overrides[request.promptVersion] ?? defaultOutput(request.promptVersion);
      const output = typeof override === "function" ? override(request) : override;
      return {
        output,
        metadata: model(request.promptVersion),
      };
    },
  };
}

function defaultOutput(promptVersion) {
  if (promptVersion === "lite-intake-v1") {
    return {
      input_type: "question",
      normalized_input: "Did the policy take effect on March 1, 2024?",
      accepted: true,
      confidence: 0.91,
      uncertainty: [],
    };
  }
  if (promptVersion === "lite-query-planner-v1") {
    return {
      embedding_text: "policy effective date March 1 2024",
      lexical_terms: ["policy", "effective", "March", "2024"],
      entity_filters: {},
      query_variants: ["policy took effect March 1 2024"],
      confidence: 0.86,
      uncertainty: [],
    };
  }
  throw new Error(`No fake output registered for ${promptVersion}`);
}

function chunk(id, text) {
  return {
    corpus_version: corpusVersion,
    chunk_id: id,
    document_id: "doc-policy",
    source_label: "Demo Source, section 1",
    source_title: "Demo Source",
    source_url: "https://example.com/demo-source",
    publisher: "Example Publisher",
    document_date: "2024-03-01",
    reviewed_at: reviewedAt,
    chunk_text: text,
    heading_path: "Section 1",
    page_or_position: "section 1",
    paragraph_index: 0,
    content_hash: `hash-${id}`,
    retrieval_scores: {
      semantic: 0.8,
      lexical: 0.75,
      metadata: 1,
      combined: 0.82,
      low_confidence: false,
    },
    retrieval_strategy: retrievalStrategyFixture(),
    metadata: {},
  };
}

function retrievalStrategyFixture() {
  return {
    name: "hybrid_pgvector_lexical",
    version: "lite-retrieval-v1",
    semantic_top_k: 24,
    lexical_top_k: 24,
    final_top_k: 8,
    min_similarity: 0.35,
    filters: { corpus_version: corpusVersion, visibility: "public" },
  };
}

function reportMetadata(promptVersions, retrievalStrategy) {
  return {
    evidence_reviewed_at: reviewedAt,
    methodology_version: "lite-methodology-v1",
    workflow_version: "lite-rag-workflow-v1",
    model_versions: { synthesis: "deepseek-chat-test" },
    prompt_versions: promptVersions,
    parser_versions: { structured_json: "zod-v4" },
    retrieval_versions: { lite: retrievalStrategy.version },
    score_roles: {},
    limitations: ["Lite Mode uses a curated stored evidence library and is not the complete production verifier."],
  };
}

function model(promptVersion) {
  return {
    provider: "deepseek",
    model: "deepseek-chat-test",
    prompt_version: promptVersion,
    temperature: 0,
    latency_ms: 12,
    token_usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
    generated_at: reviewedAt,
  };
}

async function findClientFiles(directories) {
  const files = await listFiles(directories);
  const clientFiles = [];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    if (/^\s*["']use client["'];/.test(source)) {
      clientFiles.push(file);
    }
  }
  return clientFiles;
}

async function listFiles(directories) {
  const files = [];
  for (const directory of directories) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        files.push(...(await listFiles([path])));
      } else if ([".ts", ".tsx", ".js", ".jsx"].includes(extname(entry.name))) {
        files.push(path);
      }
    }
  }
  return files;
}

function rel(file) {
  return relative(repoRoot, file).split(sep).join("/");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
