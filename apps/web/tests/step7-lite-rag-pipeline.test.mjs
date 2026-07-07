import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const tempRoot = join(root, "tests", ".tmp", `lite-step7-${process.pid}`);

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
    const outputPath = join(moduleDir, file.replace(/\.ts$/, ".js"));
    await mkdir(dirname(outputPath), { recursive: true });
    await writeFile(outputPath, output.outputText, "utf8");
  }

  return {
    pipeline: require(join(moduleDir, "pipeline.js")),
    synthesisPrompt: require(join(moduleDir, "prompts", "synthesis.js")),
  };
}

const modules = compileLiteModules();
const reviewedAt = "2026-07-07T12:00:00.000Z";
const request = {
  corpus_version: "lite-corpus-v1",
  input: "Did the policy take effect on March 1, 2024?",
  input_type_hint: "question",
};

test.after(async () => {
  await rm(tempRoot, { recursive: true, force: true });
});

test("Lite RAG pipeline returns a successful cited answer", async () => {
  const { pipeline } = await modules;
  const client = fakeClient({
    "lite-evidence-judge-v1": {
      judgments: [
        {
          chunk_id: "chunk-support",
          stance: "supports",
          cited_span: "took effect on March 1, 2024",
          rationale: "The passage directly states the effective date.",
          confidence: 0.92,
          uncertainty: [],
        },
      ],
    },
    "lite-synthesis-v1": {
      status: "answer",
      answer_markdown: "The curated evidence says the policy took effect on March 1, 2024.",
      cited_sentences: [
        {
          sentence_index: 0,
          text: "The curated evidence says the policy took effect on March 1, 2024.",
          citation_ids: ["chunk-support"],
          confidence: 0.9,
          uncertainty: [],
        },
      ],
      limitations: ["Lite Mode answers from a curated stored evidence library."],
      confidence: 0.88,
      uncertainty: [],
    },
    "lite-citation-audit-v1": {
      sentence_support: [
        {
          sentence_index: 0,
          citation_id: "chunk-support",
          support_status: "supported",
          reason: "The cited chunk states the same effective date.",
          confidence: 0.94,
        },
      ],
    },
  });

  const response = await pipeline.answerLiteClaim({
    request,
    reviewedAt,
    runId: "lite-test-success",
    deepseekClient: client,
    retrieveChunks: async () => [chunk("chunk-support", "The policy took effect on March 1, 2024, after notice.")],
  });

  assert.equal(response.kind, "answer");
  assert.equal(response.audit_status, "passed");
  assert.equal(response.cited_sentences[0].citation_ids[0], "chunk-support");
  assert.equal(response.prompt_versions.intake, "lite-intake-v1");
  assert.equal(response.prompt_versions.query_planner, "lite-query-planner-v1");
  assert.equal(response.prompt_versions.evidence_judge, "lite-evidence-judge-v1");
  assert.equal(response.prompt_versions.synthesis, "lite-synthesis-v1");
  assert.equal(response.prompt_versions.citation_audit, "lite-citation-audit-v1");
  assert.equal(response.model_metadata.stages.synthesis.token_usage.total_tokens, 18);
});

test("Lite RAG pipeline can answer with direct contradiction evidence", async () => {
  const { pipeline } = await modules;
  const client = fakeClient({
    "lite-evidence-judge-v1": {
      judgments: [
        {
          chunk_id: "chunk-contradiction",
          stance: "contradicts",
          cited_span: "the policy had not taken effect",
          rationale: "The passage says the policy was not yet effective.",
          confidence: 0.9,
          uncertainty: [],
        },
      ],
    },
    "lite-synthesis-v1": {
      status: "answer",
      answer_markdown: "The selected Lite evidence contradicts the claim: the policy had not taken effect by March 1, 2024.",
      cited_sentences: [
        {
          sentence_index: 0,
          text: "The selected Lite evidence contradicts the claim: the policy had not taken effect by March 1, 2024.",
          citation_ids: ["chunk-contradiction"],
          confidence: 0.87,
          uncertainty: [],
        },
      ],
      limitations: [],
      confidence: 0.82,
      uncertainty: [],
    },
    "lite-citation-audit-v1": {
      sentence_support: [
        {
          sentence_index: 0,
          citation_id: "chunk-contradiction",
          support_status: "supported",
          reason: "The cited chunk directly contradicts the effective-date claim.",
          confidence: 0.92,
        },
      ],
    },
  });

  const response = await pipeline.answerLiteClaim({
    request,
    reviewedAt,
    runId: "lite-test-contradiction",
    deepseekClient: client,
    retrieveChunks: async () =>
      [chunk("chunk-contradiction", "As of March 1, 2024, the policy had not taken effect.")],
  });

  assert.equal(response.kind, "answer");
  assert.match(response.answer_markdown, /contradicts/i);
  assert.equal(response.selected_context.judgments[0].stance, "contradicts");
});

test("Lite RAG pipeline returns insufficient evidence when only background chunks are selected", async () => {
  const { pipeline } = await modules;
  const client = fakeClient({
    "lite-evidence-judge-v1": {
      judgments: [
        {
          chunk_id: "chunk-background",
          stance: "background",
          cited_span: "policy background",
          rationale: "The passage provides context but no effective date.",
          confidence: 0.86,
          uncertainty: [],
        },
      ],
    },
    "lite-synthesis-v1": () => {
      throw new Error("synthesis should not run for background-only evidence");
    },
  });

  const response = await pipeline.answerLiteClaim({
    request,
    reviewedAt,
    runId: "lite-test-insufficient",
    deepseekClient: client,
    retrieveChunks: async () => [chunk("chunk-background", "The policy background was discussed by the committee.")],
  });

  assert.equal(response.kind, "insufficient_evidence");
  assert.equal(response.audit_status, "insufficient_evidence");
  assert.match(response.gaps[0], /background|weak|irrelevant/i);
});

test("Lite citation audit removes unsupported factual sentences", async () => {
  const { pipeline } = await modules;
  const client = fakeClient({
    "lite-evidence-judge-v1": {
      judgments: [
        {
          chunk_id: "chunk-support",
          stance: "supports",
          cited_span: "took effect on March 1, 2024",
          rationale: "The passage states the effective date.",
          confidence: 0.9,
          uncertainty: [],
        },
      ],
    },
    "lite-synthesis-v1": {
      status: "answer",
      answer_markdown:
        "The policy took effect on March 1, 2024. The rollout covered every state immediately.",
      cited_sentences: [
        {
          sentence_index: 0,
          text: "The policy took effect on March 1, 2024.",
          citation_ids: ["chunk-support"],
          confidence: 0.9,
          uncertainty: [],
        },
        {
          sentence_index: 1,
          text: "The rollout covered every state immediately.",
          citation_ids: ["chunk-support"],
          confidence: 0.8,
          uncertainty: [],
        },
      ],
      limitations: [],
      confidence: 0.84,
      uncertainty: [],
    },
    "lite-citation-audit-v1": {
      sentence_support: [
        {
          sentence_index: 0,
          citation_id: "chunk-support",
          support_status: "supported",
          reason: "The date is supported.",
          confidence: 0.94,
        },
        {
          sentence_index: 1,
          citation_id: "chunk-support",
          support_status: "unsupported",
          reason: "The cited chunk does not mention every state.",
          confidence: 0.93,
        },
      ],
    },
  });

  const response = await pipeline.answerLiteClaim({
    request,
    reviewedAt,
    runId: "lite-test-revised",
    deepseekClient: client,
    retrieveChunks: async () => [chunk("chunk-support", "The policy took effect on March 1, 2024.")],
  });

  assert.equal(response.kind, "answer");
  assert.equal(response.audit_status, "revised");
  assert.doesNotMatch(response.answer_markdown, /every state/i);
  assert.deepEqual(response.citation_audit.accepted_sentence_indices, [0]);
  assert.equal(response.citation_audit.rejected_sentences[0].support_status, "unsupported");
});

test("Lite pipeline rejects malformed model output", async () => {
  const { pipeline } = await modules;
  const response = await pipeline.answerLiteClaim({
    request,
    reviewedAt,
    runId: "lite-test-malformed",
    deepseekClient: fakeClient({
      "lite-intake-v1": {
        input_type: "definitely-not-a-valid-type",
        normalized_input: request.input,
        accepted: true,
        confidence: 0.5,
        uncertainty: [],
      },
    }),
    retrieveChunks: async () => [chunk("chunk-support", "The policy took effect on March 1, 2024.")],
  });

  assert.equal(response.kind, "error");
  assert.equal(response.status, "model_error");
  assert.equal(response.error_code, "lite_malformed_model_output");
});

test("Lite prompt context builders enforce bounded prompt budgets", async () => {
  const { synthesisPrompt } = await modules;
  const selectedContext = {
    corpus_version: "lite-corpus-v1",
    reviewed_at: reviewedAt,
    retrieval_strategy: retrievalStrategy(),
    selected_chunk_ids: Array.from({ length: 12 }, (_, index) => `chunk-${index}`),
    chunks: Array.from({ length: 12 }, (_, index) => chunk(`chunk-${index}`, "x".repeat(6000))),
    judgments: Array.from({ length: 12 }, (_, index) => ({
      prompt_version: "lite-evidence-judge-v1",
      model: model("lite-evidence-judge-v1"),
      chunk_id: `chunk-${index}`,
      source_label: "Demo Source, section 1",
      stance: "supports",
      cited_span: "x",
      rationale: "Synthetic support.",
      confidence: 0.8,
      uncertainty: [],
    })),
    context_token_budget: 6000,
    selection_reason: "Synthetic oversized prompt test.",
    confidence: 0.8,
    uncertainty: [],
  };

  assert.throws(
    () =>
      synthesisPrompt.buildLiteSynthesisContext(
        request,
        {
          prompt_version: "lite-intake-v1",
          model: model("lite-intake-v1"),
          input_type: "question",
          normalized_input: request.input,
          accepted: true,
          confidence: 0.9,
          uncertainty: [],
        },
        selectedContext,
      ),
    (error) => error?.name === "LitePromptBudgetError" && error.reason === "context_payload_too_large",
  );
});

function fakeClient(overrides = {}) {
  return {
    embeddingAvailable: false,
    async generateEmbeddings() {
      throw new Error("embeddings should not run in Step 7 tests");
    },
    createLexicalMetadataFallback() {
      return { kind: "lexical_metadata_fallback" };
    },
    async generateStructured(request) {
      const override = overrides[request.promptVersion] ?? defaultOutput(request.promptVersion);
      const output = typeof override === "function" ? override(request) : override;
      return {
        output,
        metadata: {
          provider: "deepseek",
          model: "deepseek-chat-test",
          prompt_version: request.promptVersion,
          temperature: request.temperature ?? 0,
          latency_ms: 12,
          token_usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
          generated_at: reviewedAt,
        },
      };
    },
  };
}

function defaultOutput(promptVersion) {
  if (promptVersion === "lite-intake-v1") {
    return {
      input_type: "question",
      normalized_input: request.input,
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

function chunk(id, text, options = {}) {
  return {
    corpus_version: "lite-corpus-v1",
    chunk_id: id,
    document_id: options.document_id ?? "doc-policy",
    source_label: options.source_label ?? "Demo Source, section 1",
    source_title: options.source_title ?? "Demo Source",
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
    retrieval_strategy: retrievalStrategy(),
    metadata: {},
  };
}

function retrievalStrategy() {
  return {
    name: "hybrid_pgvector_lexical",
    version: "lite-retrieval-v1",
    semantic_top_k: 24,
    lexical_top_k: 24,
    final_top_k: 8,
    min_similarity: 0.35,
    filters: { corpus_version: "lite-corpus-v1", visibility: "public" },
  };
}

function model(promptVersion) {
  return {
    provider: "deepseek",
    model: "deepseek-chat-test",
    temperature: 0,
    latency_ms: 12,
    token_usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
    generated_at: reviewedAt,
  };
}
