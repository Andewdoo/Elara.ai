import { z } from "zod";

export const SUPPORTED_LITE_CORPUS_VERSIONS = ["lite-corpus-v1"] as const;

export const LITE_REQUEST_MAX_LENGTH = 4000;

export const liteCorpusVersionSchema = z.enum(SUPPORTED_LITE_CORPUS_VERSIONS);

const isoDateTimeSchema = z.string().datetime({ offset: true });
const confidenceSchema = z.number().min(0).max(1);
const uncertaintySchema = z.array(z.string().trim().min(1).max(240)).max(12);
const metadataSchema = z.record(z.string(), z.unknown());
const promptVersionSchema = z.string().trim().min(1).max(80);

export const liteAuditStatusSchema = z.enum([
  "not_run",
  "passed",
  "rejected",
  "revised",
  "insufficient_evidence",
  "error",
]);

export const liteInputTypeSchema = z.enum([
  "claim",
  "question",
  "quote",
  "paraphrase",
  "unsupported_request",
]);

export const liteRetrievalStrategySchema = z.object({
  name: z.enum(["hybrid_pgvector_lexical", "lexical_metadata", "metadata_only"]),
  version: z.string().trim().min(1).max(80),
  semantic_top_k: z.number().int().positive().max(50).optional(),
  lexical_top_k: z.number().int().positive().max(50).optional(),
  final_top_k: z.number().int().positive().max(20),
  min_similarity: z.number().min(0).max(1).optional(),
  filters: metadataSchema.default({}),
});

export const liteTokenUsageSchema = z
  .object({
    input_tokens: z.number().int().nonnegative(),
    output_tokens: z.number().int().nonnegative(),
    total_tokens: z.number().int().nonnegative(),
  })
  .superRefine((value, context) => {
    if (value.total_tokens < value.input_tokens + value.output_tokens) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "total_tokens must include input_tokens and output_tokens",
        path: ["total_tokens"],
      });
    }
  });

export const liteModelMetadataSchema = z.object({
  provider: z.literal("deepseek"),
  model: z.string().trim().min(1).max(120),
  temperature: z.number().min(0).max(2).optional(),
  latency_ms: z.number().int().nonnegative().optional(),
  token_usage: liteTokenUsageSchema.optional(),
  generated_at: isoDateTimeSchema.optional(),
});

export const litePromptVersionsSchema = z.object({
  intake: promptVersionSchema.optional(),
  query_planner: promptVersionSchema.optional(),
  evidence_judge: promptVersionSchema.optional(),
  synthesis: promptVersionSchema.optional(),
  citation_audit: promptVersionSchema.optional(),
});

export const liteClaimRequestSchema = z.object({
  corpus_version: liteCorpusVersionSchema,
  input: z.string().trim().min(3).max(LITE_REQUEST_MAX_LENGTH),
  input_type_hint: z.enum(["claim", "question", "quote", "paraphrase"]).optional(),
  client_trace_id: z.string().trim().min(1).max(128).optional(),
});

export const liteInputClassificationSchema = z.object({
  prompt_version: promptVersionSchema,
  model: liteModelMetadataSchema,
  input_type: liteInputTypeSchema,
  normalized_input: z.string().trim().min(1).max(LITE_REQUEST_MAX_LENGTH),
  accepted: z.boolean(),
  rejection_reason: z.string().trim().min(1).max(400).optional(),
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
});

export const liteQueryPlanSchema = z.object({
  prompt_version: promptVersionSchema,
  model: liteModelMetadataSchema,
  corpus_version: liteCorpusVersionSchema,
  retrieval_strategy: liteRetrievalStrategySchema,
  embedding_text: z.string().trim().min(1).max(1600),
  lexical_terms: z.array(z.string().trim().min(1).max(80)).max(40).default([]),
  entity_filters: metadataSchema.default({}),
  query_variants: z.array(z.string().trim().min(1).max(240)).max(8).default([]),
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
});

export const liteRetrievedChunkSchema = z.object({
  corpus_version: liteCorpusVersionSchema,
  chunk_id: z.string().trim().min(1).max(160),
  document_id: z.string().trim().min(1).max(160),
  source_label: z.string().trim().min(1).max(120),
  source_title: z.string().trim().min(1).max(240),
  source_url: z.string().url().optional(),
  publisher: z.string().trim().min(1).max(160).optional(),
  document_date: z.string().trim().min(1).max(80).optional(),
  reviewed_at: isoDateTimeSchema,
  chunk_text: z.string().trim().min(1).max(6000),
  heading_path: z.string().trim().min(1).max(240).optional(),
  page_or_position: z.string().trim().min(1).max(120).optional(),
  paragraph_index: z.number().int().nonnegative().optional(),
  content_hash: z.string().trim().min(8).max(160),
  retrieval_scores: z.object({
    semantic: confidenceSchema.optional(),
    lexical: confidenceSchema.optional(),
    metadata: confidenceSchema.optional(),
    combined: confidenceSchema,
    low_confidence: z.boolean().optional(),
  }),
  retrieval_strategy: liteRetrievalStrategySchema,
  metadata: metadataSchema.default({}),
});

export const liteEvidenceJudgmentSchema = z.object({
  prompt_version: promptVersionSchema,
  model: liteModelMetadataSchema,
  chunk_id: z.string().trim().min(1).max(160),
  source_label: z.string().trim().min(1).max(120),
  stance: z.enum(["supports", "contradicts", "background", "irrelevant"]),
  cited_span: z.string().trim().min(1).max(1200).optional(),
  rationale: z.string().trim().min(1).max(600).optional(),
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
});

export const liteSelectedContextSchema = z
  .object({
    corpus_version: liteCorpusVersionSchema,
    reviewed_at: isoDateTimeSchema,
    retrieval_strategy: liteRetrievalStrategySchema,
    selected_chunk_ids: z.array(z.string().trim().min(1).max(160)).min(1).max(12),
    chunks: z.array(liteRetrievedChunkSchema).min(1).max(12),
    judgments: z.array(liteEvidenceJudgmentSchema).max(24).default([]),
    context_token_budget: z.number().int().positive().max(24000),
    selection_reason: z.string().trim().min(1).max(600),
    confidence: confidenceSchema,
    uncertainty: uncertaintySchema.default([]),
  })
  .superRefine((value, context) => {
    const availableChunkIds = new Set(value.chunks.map((chunk) => chunk.chunk_id));
    for (const chunkId of value.selected_chunk_ids) {
      if (!availableChunkIds.has(chunkId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "selected_chunk_ids must reference included chunks",
          path: ["selected_chunk_ids"],
        });
      }
    }
  });

export const liteCitedSentenceSchema = z.object({
  sentence_index: z.number().int().nonnegative(),
  text: z.string().trim().min(1).max(1200),
  citation_ids: z.array(z.string().trim().min(1).max(160)).min(1).max(8),
  source_labels: z.array(z.string().trim().min(1).max(120)).min(1).max(8),
  support_status: z.enum(["supported", "partially_supported", "unsupported", "missing_citation"]),
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
});

export const liteSynthesisOutputSchema = z
  .object({
    prompt_version: promptVersionSchema,
    model: liteModelMetadataSchema,
    status: z.enum(["answer", "insufficient_evidence"]),
    answer_markdown: z.string().trim().min(1).max(8000),
    cited_sentences: z.array(liteCitedSentenceSchema).max(40),
    limitations: z.array(z.string().trim().min(1).max(400)).max(12).default([]),
    confidence: confidenceSchema,
    uncertainty: uncertaintySchema.default([]),
  })
  .superRefine((value, context) => {
    if (value.status === "answer" && value.cited_sentences.length === 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "answer synthesis requires cited sentences",
        path: ["cited_sentences"],
      });
    }
  });

export const liteCitationAuditOutputSchema = z.object({
  prompt_version: promptVersionSchema,
  model: liteModelMetadataSchema,
  audit_status: liteAuditStatusSchema,
  checked_sentence_count: z.number().int().nonnegative(),
  accepted_sentence_indices: z.array(z.number().int().nonnegative()).max(80).default([]),
  rejected_sentences: z
    .array(
      z.object({
        sentence_index: z.number().int().nonnegative(),
        text: z.string().trim().min(1).max(1200),
        citation_ids: z.array(z.string().trim().min(1).max(160)).max(8).default([]),
        reason: z.string().trim().min(1).max(500),
        support_status: z.enum(["unsupported", "missing_citation", "unknown_chunk", "partial"]),
      }),
    )
    .max(80)
    .default([]),
  missing_citation_sentence_indices: z.array(z.number().int().nonnegative()).max(80).default([]),
  unknown_chunk_ids: z.array(z.string().trim().min(1).max(160)).max(80).default([]),
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
});

export const liteReportMetadataSchema = z.object({
  evidence_reviewed_at: isoDateTimeSchema,
  methodology_version: z.string().trim().min(1).max(80),
  workflow_version: z.string().trim().min(1).max(80),
  model_versions: z.record(z.string(), z.string().trim().min(1).max(120)),
  prompt_versions: litePromptVersionsSchema,
  parser_versions: z.record(z.string(), z.string().trim().min(1).max(120)).default({}),
  retrieval_versions: z.record(z.string(), z.string().trim().min(1).max(120)),
  score_roles: z.record(z.string(), z.string().trim().min(1).max(120)).default({}),
  limitations: z.array(z.string().trim().min(1).max(400)).max(12).default([]),
});

const liteBaseResponseSchema = z.object({
  run_id: z.string().trim().min(1).max(160),
  corpus_version: liteCorpusVersionSchema,
  reviewed_at: isoDateTimeSchema,
  request: liteClaimRequestSchema,
  classification: liteInputClassificationSchema.optional(),
  query_plan: liteQueryPlanSchema.optional(),
  retrieval_strategy: liteRetrievalStrategySchema,
  chunk_ids: z.array(z.string().trim().min(1).max(160)).max(20),
  source_labels: z.array(z.string().trim().min(1).max(120)).max(20),
  model_metadata: z.object({
    provider: z.literal("deepseek"),
    stages: z.record(z.string(), liteModelMetadataSchema),
  }),
  prompt_versions: litePromptVersionsSchema,
  report_metadata: liteReportMetadataSchema,
  confidence: confidenceSchema,
  uncertainty: uncertaintySchema.default([]),
  audit_status: liteAuditStatusSchema,
});

export const liteAnswerResponseSchema = liteBaseResponseSchema
  .extend({
    kind: z.literal("answer"),
    status: z.literal("answered"),
    selected_context: liteSelectedContextSchema,
    synthesis: liteSynthesisOutputSchema,
    citation_audit: liteCitationAuditOutputSchema,
    answer_markdown: z.string().trim().min(1).max(8000),
    cited_sentences: z.array(liteCitedSentenceSchema).min(1).max(40),
  })
  .superRefine((value, context) => {
    if (!["passed", "revised"].includes(value.audit_status)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "answered Lite responses require a passed or revised citation audit",
        path: ["audit_status"],
      });
    }
  });

export const liteInsufficientEvidenceResponseSchema = liteBaseResponseSchema.extend({
  kind: z.literal("insufficient_evidence"),
  status: z.literal("insufficient_evidence"),
  selected_context: liteSelectedContextSchema.optional(),
  synthesis: liteSynthesisOutputSchema.optional(),
  citation_audit: liteCitationAuditOutputSchema.optional(),
  message: z.string().trim().min(1).max(800),
  gaps: z.array(z.string().trim().min(1).max(400)).max(12).default([]),
  audit_status: z.literal("insufficient_evidence"),
});

export const liteErrorResponseSchema = z.object({
  kind: z.literal("error"),
  status: z.enum([
    "invalid_request",
    "unsupported_request",
    "retrieval_error",
    "model_error",
    "audit_error",
    "internal_error",
  ]),
  request_id: z.string().trim().min(1).max(160).optional(),
  corpus_version: liteCorpusVersionSchema.optional(),
  reviewed_at: isoDateTimeSchema.optional(),
  error_code: z.string().trim().min(1).max(120),
  message: z.string().trim().min(1).max(800),
  retryable: z.boolean(),
  audit_status: z.enum(["not_run", "error"]),
});

export const liteResponseSchema = z.discriminatedUnion("kind", [
  liteAnswerResponseSchema,
  liteInsufficientEvidenceResponseSchema,
  liteErrorResponseSchema,
]);

export type LiteClaimRequest = z.infer<typeof liteClaimRequestSchema>;
export type LiteModelMetadata = z.infer<typeof liteModelMetadataSchema>;
export type LiteInputClassification = z.infer<typeof liteInputClassificationSchema>;
export type LiteQueryPlan = z.infer<typeof liteQueryPlanSchema>;
export type LiteRetrievedChunk = z.infer<typeof liteRetrievedChunkSchema>;
export type LiteEvidenceJudgment = z.infer<typeof liteEvidenceJudgmentSchema>;
export type LiteSelectedContext = z.infer<typeof liteSelectedContextSchema>;
export type LiteCitedSentence = z.infer<typeof liteCitedSentenceSchema>;
export type LiteSynthesisOutput = z.infer<typeof liteSynthesisOutputSchema>;
export type LiteCitationAuditOutput = z.infer<typeof liteCitationAuditOutputSchema>;
export type LiteAnswerResponse = z.infer<typeof liteAnswerResponseSchema>;
export type LiteInsufficientEvidenceResponse = z.infer<typeof liteInsufficientEvidenceResponseSchema>;
export type LiteErrorResponse = z.infer<typeof liteErrorResponseSchema>;
export type LiteResponse = z.infer<typeof liteResponseSchema>;
