import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, "tests", ".tmp", `lite-step8-${process.pid}`);
const reviewedAt = "2026-07-07T12:00:00.000Z";
const corpusVersion = "lite-corpus-v1";
const runId = "11111111-1111-4111-8111-111111111111";
const chunkId = "22222222-2222-4222-8222-222222222222";

async function compileRouteModule() {
  const ts = require("typescript");
  await mkdir(join(tempRoot, "lib", "lite"), { recursive: true });
  await mkdir(join(tempRoot, "app", "api", "lite", "answer"), { recursive: true });
  await mkdir(join(tempRoot, "fakes"), { recursive: true });
  await writeFile(join(tempRoot, "package.json"), "{\"type\":\"commonjs\"}", "utf8");
  await writeFile(join(tempRoot, "fakes", "pipeline.js"), "exports.answerLiteClaim = async () => { throw new Error('inject pipeline'); };\n", "utf8");
  await writeFile(
    join(tempRoot, "fakes", "run-persistence.js"),
    "exports.persistLiteRunIfConfigured = async () => 'skipped';\n",
    "utf8",
  );

  for (const file of ["schemas.ts", "server-config.ts", "supabase.ts", "run-persistence.ts"]) {
    await transpile(ts, join(root, "lib", "lite", file), join(tempRoot, "lib", "lite", file.replace(/\.ts$/, ".js")));
  }
  const routeSource = (await readFile(join(root, "app", "api", "lite", "answer", "route.ts"), "utf8"))
    .replace("@/lib/lite/pipeline", "../../../../fakes/pipeline.js")
    .replace("@/lib/lite/run-persistence", "../../../../fakes/run-persistence.js")
    .replace("@/lib/lite/schemas", "../../../../lib/lite/schemas.js");
  await transpileSource(
    ts,
    routeSource,
    join(root, "app", "api", "lite", "answer", "route.ts"),
    join(tempRoot, "app", "api", "lite", "answer", "route.js"),
  );

  return {
    route: require(join(tempRoot, "app", "api", "lite", "answer", "route.js")),
    persistence: require(join(tempRoot, "lib", "lite", "run-persistence.js")),
  };
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

const routeModule = compileRouteModule();

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite API route returns a typed successful answer and persists through the injected server boundary", async () => {
  const { route } = await routeModule;
  const persisted = [];
  const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest()), {
    runIdFactory: () => runId,
    answerLiteClaim: async (options) => answerResponse(options.runId),
    persistLiteRunIfConfigured: async (result) => {
      persisted.push(result);
      return "persisted";
    },
    rateBuckets: new Map(),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.kind, "answer");
  assert.equal(body.run_id, runId);
  assert.equal(body.cited_sentences[0].citation_ids[0], chunkId);
  assert.equal(persisted.length, 1);
  assert.equal(persisted[0].kind, "answer");
});

test("Lite API route returns insufficient evidence without treating it as a route failure", async () => {
  const { route } = await routeModule;
  const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest({ input: "What does the corpus say about an uncovered topic?" })), {
    runIdFactory: () => runId,
    answerLiteClaim: async (options) => insufficientResponse(options.runId, ["The selected chunks were background only."]),
    persistLiteRunIfConfigured: async () => "skipped",
    rateBuckets: new Map(),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.kind, "insufficient_evidence");
  assert.match(body.gaps[0], /background/i);
});

test("Lite API route handles missing curated corpus matches as insufficient evidence", async () => {
  const { route } = await routeModule;
  const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest()), {
    runIdFactory: () => runId,
    answerLiteClaim: async (options) => insufficientResponse(options.runId, ["No curated Lite corpus chunks matched the request."]),
    persistLiteRunIfConfigured: async () => "skipped",
    rateBuckets: new Map(),
  });
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.kind, "insufficient_evidence");
  assert.match(body.gaps[0], /No curated Lite corpus chunks/i);
});

test("Lite API route rejects bad input before the pipeline runs", async () => {
  const { route } = await routeModule;
  let pipelineCalls = 0;
  const response = await route.handleLiteAnswerRequest(jsonRequest({ corpus_version: corpusVersion, input: "no" }), {
    answerLiteClaim: async () => {
      pipelineCalls += 1;
      return answerResponse(runId);
    },
    rateBuckets: new Map(),
  });
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.equal(body.kind, "error");
  assert.equal(body.error_code, "lite_invalid_request");
  assert.equal(pipelineCalls, 0);
});

test("Lite API route maps provider failures to sanitized public errors", async () => {
  const { route } = await routeModule;
  const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest()), {
    runIdFactory: () => runId,
    answerLiteClaim: async () => ({
      kind: "error",
      status: "model_error",
      request_id: runId,
      corpus_version: corpusVersion,
      reviewed_at: reviewedAt,
      error_code: "deepseek_authentication_error",
      message: "DEEPSEEK_API_KEY=server-secret leaked provider body",
      retryable: true,
      audit_status: "error",
    }),
    persistLiteRunIfConfigured: async () => "not_persistable",
    rateBuckets: new Map(),
  });
  const text = await response.text();

  assert.equal(response.status, 503);
  assert.match(text, /server-side Lite provider failed/i);
  assert.doesNotMatch(text, /server-secret|DEEPSEEK_API_KEY|provider body/);
});

test("Lite API route does not expose Supabase service-role details when persistence fails", async () => {
  const { route } = await routeModule;
  const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest()), {
    runIdFactory: () => runId,
    answerLiteClaim: async (options) => answerResponse(options.runId),
    persistLiteRunIfConfigured: async () => {
      throw new Error("SUPABASE_SERVICE_ROLE_KEY=service-secret private prompt text");
    },
    rateBuckets: new Map(),
  });
  const text = await response.text();

  assert.equal(response.status, 503);
  assert.match(text, /could not safely store/i);
  assert.doesNotMatch(text, /service-secret|SUPABASE_SERVICE_ROLE_KEY|private prompt/);
});

test("Lite API route enforces simple public-demo rate and abuse limits", async () => {
  const { route } = await routeModule;
  const rateBuckets = new Map();
  let pipelineCalls = 0;
  for (let index = 0; index < 8; index += 1) {
    const response = await route.handleLiteAnswerRequest(jsonRequest(validRequest(), { "x-forwarded-for": "203.0.113.10" }), {
      runIdFactory: () => runId,
      answerLiteClaim: async (options) => {
        pipelineCalls += 1;
        return insufficientResponse(options.runId, ["Fixture response."]);
      },
      persistLiteRunIfConfigured: async () => "skipped",
      now: () => 1000,
      rateBuckets,
    });
    assert.equal(response.status, 200);
  }

  const limited = await route.handleLiteAnswerRequest(jsonRequest(validRequest(), { "x-forwarded-for": "203.0.113.10" }), {
    answerLiteClaim: async () => answerResponse(runId),
    now: () => 1000,
    rateBuckets,
  });
  const abusive = await route.handleLiteAnswerRequest(jsonRequest(validRequest({ input: "A".repeat(900) })), {
    answerLiteClaim: async () => answerResponse(runId),
    rateBuckets: new Map(),
  });

  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("retry-after"), "60");
  assert.equal(abusive.status, 422);
  assert.equal(pipelineCalls, 8);
});

test("Lite run persistence maps non-sensitive run and citation records when Supabase is configured", async () => {
  const { persistence } = await routeModule;
  const insertedRuns = [];
  const insertedCitations = [];

  const result = await persistence.persistLiteRunIfConfigured(answerResponse(runId), {
    env: {
      SUPABASE_URL: "https://supabase.example.test",
      SUPABASE_SERVICE_ROLE_KEY: "service-role-secret",
    },
    supabaseClient: {
      async insertLiteRun(row) {
        insertedRuns.push(row);
      },
      async insertLiteRunCitations(rows) {
        insertedCitations.push(...rows);
      },
    },
  });

  assert.equal(result, "persisted");
  assert.equal(insertedRuns.length, 1);
  assert.equal(insertedRuns[0].id, runId);
  assert.equal(insertedRuns[0].answer_status, "answered");
  assert.equal(insertedRuns[0].model_provider, "deepseek");
  assert.deepEqual(insertedRuns[0].retrieval_metadata.chunk_ids, [chunkId]);
  assert.doesNotMatch(JSON.stringify(insertedRuns[0]), /chunk_text|system prompt|service-role-secret/i);
  assert.equal(insertedCitations.length, 1);
  assert.equal(insertedCitations[0].run_id, runId);
  assert.equal(insertedCitations[0].chunk_id, chunkId);
  assert.equal(insertedCitations[0].support_status, "support");
  assert.equal(insertedCitations[0].audit_status, "passed");
});

test("Lite API route source keeps Full Mode services and private credential names out of the boundary", async () => {
  const source = await readFile(join(root, "app", "api", "lite", "answer", "route.ts"), "utf8");

  assert.doesNotMatch(source, /FastAPI|\/v1\/verifications|Redis|Celery|Brave|Firebase Admin|firebase-admin|S3/i);
  assert.doesNotMatch(source, /SUPABASE_SERVICE_ROLE_KEY|DEEPSEEK_API_KEY/);
});

function jsonRequest(body, headers = {}) {
  return new Request("https://elara.example.test/api/lite/answer", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

function validRequest(overrides = {}) {
  return {
    corpus_version: corpusVersion,
    input: "Did the policy take effect on March 1, 2024?",
    input_type_hint: "question",
    client_trace_id: "trace-step8",
    ...overrides,
  };
}

function answerResponse(id) {
  const request = validRequest();
  const retrievalStrategy = {
    name: "hybrid_pgvector_lexical",
    version: "lite-retrieval-v1",
    semantic_top_k: 24,
    lexical_top_k: 24,
    final_top_k: 8,
    min_similarity: 0.35,
    filters: { corpus_version: corpusVersion, visibility: "public" },
  };
  const modelMetadata = model("lite-synthesis-v1");
  const chunk = liteChunk(retrievalStrategy);
  const classification = {
    prompt_version: "lite-intake-v1",
    model: model("lite-intake-v1"),
    input_type: "question",
    normalized_input: request.input,
    accepted: true,
    confidence: 0.91,
    uncertainty: [],
  };
  const queryPlan = {
    prompt_version: "lite-query-planner-v1",
    model: model("lite-query-planner-v1"),
    corpus_version: corpusVersion,
    retrieval_strategy: retrievalStrategy,
    embedding_text: "policy effective date March 1 2024",
    lexical_terms: ["policy", "effective", "March", "2024"],
    entity_filters: {},
    query_variants: ["policy took effect March 1 2024"],
    confidence: 0.86,
    uncertainty: [],
  };
  const selectedContext = {
    corpus_version: corpusVersion,
    reviewed_at: reviewedAt,
    retrieval_strategy: retrievalStrategy,
    selected_chunk_ids: [chunkId],
    chunks: [chunk],
    judgments: [
      {
        prompt_version: "lite-evidence-judge-v1",
        model: model("lite-evidence-judge-v1"),
        chunk_id: chunkId,
        source_label: chunk.source_label,
        stance: "supports",
        cited_span: "took effect on March 1, 2024",
        rationale: "The passage states the effective date.",
        confidence: 0.9,
        uncertainty: [],
      },
    ],
    context_token_budget: 6000,
    selection_reason: "Fixture selected direct support.",
    confidence: 0.85,
    uncertainty: [],
  };
  const citedSentence = {
    sentence_index: 0,
    text: "The curated evidence says the policy took effect on March 1, 2024.",
    citation_ids: [chunkId],
    source_labels: [chunk.source_label],
    support_status: "supported",
    confidence: 0.9,
    uncertainty: [],
  };
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
    request,
    classification,
    query_plan: queryPlan,
    retrieval_strategy: retrievalStrategy,
    chunk_ids: [chunkId],
    source_labels: [chunk.source_label],
    model_metadata: {
      provider: "deepseek",
      stages: {
        intake: classification.model,
        query_planner: queryPlan.model,
        evidence_judge: selectedContext.judgments[0].model,
        synthesis: modelMetadata,
        citation_audit: model("lite-citation-audit-v1"),
      },
    },
    prompt_versions: promptVersions,
    report_metadata: reportMetadata(promptVersions, retrievalStrategy),
    confidence: 0.82,
    uncertainty: [],
    audit_status: "passed",
    selected_context: selectedContext,
    synthesis: {
      prompt_version: "lite-synthesis-v1",
      model: modelMetadata,
      status: "answer",
      answer_markdown: citedSentence.text,
      cited_sentences: [citedSentence],
      limitations: ["Lite Mode answers from a curated stored evidence library."],
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

function insufficientResponse(id, gaps) {
  const request = validRequest();
  const retrievalStrategy = {
    name: "lexical_metadata",
    version: "lite-retrieval-v1",
    lexical_top_k: 8,
    final_top_k: 8,
    filters: { corpus_version: corpusVersion, visibility: "public" },
  };
  const promptVersions = {
    intake: "lite-intake-v1",
    query_planner: "lite-query-planner-v1",
  };
  return {
    kind: "insufficient_evidence",
    status: "insufficient_evidence",
    run_id: id,
    corpus_version: corpusVersion,
    reviewed_at: reviewedAt,
    request,
    retrieval_strategy: retrievalStrategy,
    chunk_ids: [],
    source_labels: [],
    model_metadata: { provider: "deepseek", stages: { intake: model("lite-intake-v1") } },
    prompt_versions: promptVersions,
    report_metadata: reportMetadata(promptVersions, retrievalStrategy),
    confidence: 0.35,
    uncertainty: ["Lite Mode answers only from selected stored corpus chunks."],
    audit_status: "insufficient_evidence",
    message: "The curated Lite evidence library does not contain enough direct evidence to answer this without overreaching.",
    gaps,
  };
}

function liteChunk(retrievalStrategy) {
  return {
    corpus_version: corpusVersion,
    chunk_id: chunkId,
    document_id: "33333333-3333-4333-8333-333333333333",
    source_label: "Demo Source, section 1",
    source_title: "Demo Source",
    source_url: "https://example.com/demo-source",
    publisher: "Example Publisher",
    document_date: "2024-03-01",
    reviewed_at: reviewedAt,
    chunk_text: "The policy took effect on March 1, 2024, after public notice.",
    heading_path: "Section 1",
    page_or_position: "section 1",
    paragraph_index: 0,
    content_hash: "hash-22222222",
    retrieval_scores: {
      semantic: 0.8,
      lexical: 0.75,
      metadata: 1,
      combined: 0.82,
      low_confidence: false,
    },
    retrieval_strategy: retrievalStrategy,
    metadata: {},
  };
}

function reportMetadata(promptVersions, retrievalStrategy) {
  return {
    evidence_reviewed_at: reviewedAt,
    methodology_version: "lite-methodology-v1",
    workflow_version: "lite-rag-workflow-v1",
    model_versions: { intake: "deepseek-chat-test" },
    prompt_versions: promptVersions,
    parser_versions: { structured_json: "zod-v4" },
    retrieval_versions: { lite: retrievalStrategy.version },
    score_roles: {},
    limitations: ["Lite Mode uses a curated stored evidence library and is not the complete production verifier."],
  };
}

function model() {
  return {
    provider: "deepseek",
    model: "deepseek-chat-test",
    temperature: 0,
    latency_ms: 12,
    token_usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
    generated_at: reviewedAt,
  };
}
