import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));

const schemas = (async () => {
  const ts = require("typescript");
  const schemaPath = join(root, "lib", "lite", "schemas.ts");
  const source = await readFile(schemaPath, "utf8");
  const output = ts.transpileModule(source, {
    fileName: schemaPath,
    reportDiagnostics: true,
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  });

  const errors = output.diagnostics?.filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error) ?? [];
  assert.equal(errors.length, 0);

  const tempDir = join(root, "tests", ".tmp");
  const tempModule = join(tempDir, `lite-schemas-${process.pid}.cjs`);
  await mkdir(tempDir, { recursive: true });
  await writeFile(tempModule, output.outputText, "utf8");
  const loaded = require(tempModule);
  await rm(tempModule, { force: true });
  return loaded;
})();

const reviewedAt = "2026-07-07T12:00:00.000Z";

const retrievalStrategy = {
  name: "hybrid_pgvector_lexical",
  version: "lite-retrieval-v1",
  semantic_top_k: 12,
  lexical_top_k: 12,
  final_top_k: 6,
  min_similarity: 0.42,
  filters: { visibility: "public_demo" },
};

const model = {
  provider: "deepseek",
  model: "deepseek-chat",
  temperature: 0,
  latency_ms: 320,
  token_usage: { input_tokens: 100, output_tokens: 40, total_tokens: 140 },
  generated_at: reviewedAt,
};

const request = {
  corpus_version: "lite-corpus-v1",
  input: "Did the policy take effect in 2024?",
  input_type_hint: "question",
  client_trace_id: "trace-123",
};

const classification = {
  prompt_version: "lite-intake-v1",
  model,
  input_type: "question",
  normalized_input: request.input,
  accepted: true,
  confidence: 0.91,
  uncertainty: [],
};

const queryPlan = {
  prompt_version: "lite-query-plan-v1",
  model,
  corpus_version: "lite-corpus-v1",
  retrieval_strategy: retrievalStrategy,
  embedding_text: "policy effective date 2024",
  lexical_terms: ["policy", "effective", "2024"],
  entity_filters: { year: 2024 },
  query_variants: ["policy took effect in 2024"],
  confidence: 0.86,
  uncertainty: ["Corpus only covers curated demo sources."],
};

const chunk = {
  corpus_version: "lite-corpus-v1",
  chunk_id: "chunk-policy-001",
  document_id: "doc-policy",
  source_label: "Policy brief, section 2",
  source_title: "Public Policy Brief",
  source_url: "https://example.com/policy-brief",
  publisher: "Example Publisher",
  document_date: "2024-03-01",
  reviewed_at: reviewedAt,
  chunk_text: "The policy took effect on March 1, 2024, after the final notice was published.",
  heading_path: "Implementation > Effective date",
  page_or_position: "section 2",
  paragraph_index: 3,
  content_hash: "hash-123456789",
  retrieval_scores: { semantic: 0.84, lexical: 0.72, metadata: 0.5, combined: 0.8 },
  retrieval_strategy: retrievalStrategy,
  metadata: { demo: true },
};

const judgment = {
  prompt_version: "lite-evidence-judge-v1",
  model,
  chunk_id: chunk.chunk_id,
  source_label: chunk.source_label,
  stance: "supports",
  cited_span: "The policy took effect on March 1, 2024",
  rationale: "The passage directly states the effective date.",
  confidence: 0.9,
  uncertainty: [],
};

const selectedContext = {
  corpus_version: "lite-corpus-v1",
  reviewed_at: reviewedAt,
  retrieval_strategy: retrievalStrategy,
  selected_chunk_ids: [chunk.chunk_id],
  chunks: [chunk],
  judgments: [judgment],
  context_token_budget: 6000,
  selection_reason: "The chunk directly addresses the effective date.",
  confidence: 0.88,
  uncertainty: [],
};

const citedSentence = {
  sentence_index: 0,
  text: "The curated evidence says the policy took effect on March 1, 2024.",
  citation_ids: [chunk.chunk_id],
  source_labels: [chunk.source_label],
  support_status: "supported",
  confidence: 0.9,
  uncertainty: [],
};

const synthesis = {
  prompt_version: "lite-synthesis-v1",
  model,
  status: "answer",
  answer_markdown: citedSentence.text,
  cited_sentences: [citedSentence],
  limitations: ["Lite Mode answers only from the curated evidence library."],
  confidence: 0.84,
  uncertainty: [],
};

const passedAudit = {
  prompt_version: "lite-citation-audit-v1",
  model,
  audit_status: "passed",
  checked_sentence_count: 1,
  accepted_sentence_indices: [0],
  rejected_sentences: [],
  missing_citation_sentence_indices: [],
  unknown_chunk_ids: [],
  confidence: 0.92,
  uncertainty: [],
};

const reportMetadata = {
  evidence_reviewed_at: reviewedAt,
  methodology_version: "lite-methodology-v1",
  workflow_version: "lite-workflow-v1",
  model_versions: { synthesis: "deepseek-chat" },
  prompt_versions: {
    intake: "lite-intake-v1",
    query_planner: "lite-query-plan-v1",
    evidence_judge: "lite-evidence-judge-v1",
    synthesis: "lite-synthesis-v1",
    citation_audit: "lite-citation-audit-v1",
  },
  parser_versions: {},
  retrieval_versions: { lite: "lite-retrieval-v1" },
  score_roles: {},
  limitations: ["Evidence reviewed as of 2026-07-07T12:00:00.000Z. New evidence or corrections may change this assessment."],
};

const baseResponse = {
  run_id: "lite-run-123",
  corpus_version: "lite-corpus-v1",
  reviewed_at: reviewedAt,
  request,
  classification,
  query_plan: queryPlan,
  retrieval_strategy: retrievalStrategy,
  chunk_ids: [chunk.chunk_id],
  source_labels: [chunk.source_label],
  model_metadata: { provider: "deepseek", stages: { intake: model, synthesis: model, citation_audit: model } },
  prompt_versions: reportMetadata.prompt_versions,
  report_metadata: reportMetadata,
  confidence: 0.83,
  uncertainty: [],
};

test("Lite answer responses validate report-compatible cited output", async () => {
  const { liteAnswerResponseSchema } = await schemas;
  const parsed = liteAnswerResponseSchema.parse({
    ...baseResponse,
    kind: "answer",
    status: "answered",
    audit_status: "passed",
    selected_context: selectedContext,
    synthesis,
    citation_audit: passedAudit,
    answer_markdown: synthesis.answer_markdown,
    cited_sentences: [citedSentence],
  });

  assert.equal(parsed.kind, "answer");
  assert.equal(parsed.model_metadata.provider, "deepseek");
  assert.equal(parsed.report_metadata.workflow_version, "lite-workflow-v1");
  assert.deepEqual(parsed.chunk_ids, [chunk.chunk_id]);
  assert.deepEqual(parsed.source_labels, [chunk.source_label]);
});

test("Lite insufficient-evidence responses preserve corpus, retrieval, and audit status", async () => {
  const { liteInsufficientEvidenceResponseSchema } = await schemas;
  const parsed = liteInsufficientEvidenceResponseSchema.parse({
    ...baseResponse,
    kind: "insufficient_evidence",
    status: "insufficient_evidence",
    audit_status: "insufficient_evidence",
    chunk_ids: [],
    source_labels: [],
    selected_context: undefined,
    synthesis: {
      ...synthesis,
      status: "insufficient_evidence",
      answer_markdown: "The curated evidence library does not contain enough support to answer this.",
      cited_sentences: [],
      confidence: 0.34,
      uncertainty: ["No direct supporting chunk was selected."],
    },
    citation_audit: undefined,
    message: "The curated evidence library does not contain enough support to answer this.",
    gaps: ["No source in the selected corpus directly addresses the claim."],
    confidence: 0.34,
    uncertainty: ["No direct supporting chunk was selected."],
  });

  assert.equal(parsed.kind, "insufficient_evidence");
  assert.equal(parsed.audit_status, "insufficient_evidence");
  assert.equal(parsed.corpus_version, "lite-corpus-v1");
});

test("Lite citation audits can reject unsupported citations but final answers cannot pass them through", async () => {
  const { liteAnswerResponseSchema, liteCitationAuditOutputSchema } = await schemas;
  const rejectedAudit = {
    ...passedAudit,
    audit_status: "rejected",
    accepted_sentence_indices: [],
    rejected_sentences: [
      {
        sentence_index: 0,
        text: citedSentence.text,
        citation_ids: ["missing-chunk"],
        reason: "The cited chunk id was not retrieved for this response.",
        support_status: "unknown_chunk",
      },
    ],
    unknown_chunk_ids: ["missing-chunk"],
    confidence: 0.95,
  };

  assert.equal(liteCitationAuditOutputSchema.parse(rejectedAudit).audit_status, "rejected");
  assert.equal(
    liteAnswerResponseSchema.safeParse({
      ...baseResponse,
      kind: "answer",
      status: "answered",
      audit_status: "rejected",
      selected_context: selectedContext,
      synthesis,
      citation_audit: rejectedAudit,
      answer_markdown: synthesis.answer_markdown,
      cited_sentences: [citedSentence],
    }).success,
    false,
  );
});

test("Lite claim requests reject malformed and overlong input", async () => {
  const { LITE_REQUEST_MAX_LENGTH, liteClaimRequestSchema } = await schemas;

  assert.equal(liteClaimRequestSchema.safeParse({ corpus_version: "lite-corpus-v1", input: "  " }).success, false);
  assert.equal(
    liteClaimRequestSchema.safeParse({
      corpus_version: "lite-corpus-v1",
      input: "x".repeat(LITE_REQUEST_MAX_LENGTH + 1),
    }).success,
    false,
  );
});

test("Lite schemas reject unknown corpus versions", async () => {
  const { liteClaimRequestSchema, liteRetrievedChunkSchema } = await schemas;

  assert.equal(
    liteClaimRequestSchema.safeParse({
      ...request,
      corpus_version: "unknown-corpus-v9",
    }).success,
    false,
  );
  assert.equal(liteRetrievedChunkSchema.safeParse({ ...chunk, corpus_version: "unknown-corpus-v9" }).success, false);
});
