import { z } from "zod";

import { createDeepSeekClient, LiteDeepSeekError, type DeepSeekClient } from "./deepseek";
import {
  assistLiteCitationAudit,
  LITE_CITATION_AUDIT_PROMPT_VERSION,
  type LiteCitationAuditAssistance,
} from "./prompts/citation-audit";
import { judgeLiteEvidence, LITE_EVIDENCE_JUDGE_PROMPT_VERSION } from "./prompts/evidence-judge";
import { classifyLiteInput, LITE_INTAKE_PROMPT_VERSION } from "./prompts/intake";
import { planLiteQuery, LITE_QUERY_PLANNER_PROMPT_VERSION } from "./prompts/query-planner";
import { synthesizeLiteAnswer, LITE_SYNTHESIS_PROMPT_VERSION } from "./prompts/synthesis";
import { retrieveLiteChunks, type LiteRetrieveChunksOptions } from "./retrieval";
import {
  liteCitationAuditOutputSchema,
  liteClaimRequestSchema,
  liteSelectedContextSchema,
  type LiteAnswerResponse,
  type LiteCitationAuditOutput,
  type LiteClaimRequest,
  type LiteCitedSentence,
  type LiteErrorResponse,
  type LiteEvidenceJudgment,
  type LiteInputClassification,
  type LiteInsufficientEvidenceResponse,
  type LiteModelMetadata,
  type LiteQueryPlan,
  type LiteResponse,
  type LiteRetrievedChunk,
  type LiteSelectedContext,
  type LiteSynthesisOutput,
} from "./schemas";
import { assertLiteServerOnly } from "./server-config";

assertLiteServerOnly("Lite RAG pipeline");

export const LITE_RAG_WORKFLOW_VERSION = "lite-rag-workflow-v1";
export const LITE_RAG_METHODOLOGY_VERSION = "lite-methodology-v1";
export const LITE_CONTEXT_SELECTOR_VERSION = "lite-context-selector-v1";

const LITE_MIN_DIRECT_JUDGMENT_CONFIDENCE = 0.55;
const LITE_MIN_DIRECT_RETRIEVAL_SCORE = 0.32;
const LITE_CONTEXT_TOKEN_BUDGET = 6_000;
const LITE_MAX_SELECTED_CHUNKS = 8;

export type LiteRetrieveChunks = (options: LiteRetrieveChunksOptions) => Promise<LiteRetrievedChunk[]>;

export interface LitePipelineOptions {
  request: unknown;
  reviewedAt?: string;
  runId?: string;
  deepseekClient?: Pick<DeepSeekClient, "generateStructured" | "embeddingAvailable" | "generateEmbeddings" | "createLexicalMetadataFallback">;
  retrieveChunks?: LiteRetrieveChunks;
  signal?: AbortSignal;
}

interface LitePipelineState {
  request: LiteClaimRequest;
  reviewedAt: string;
  runId: string;
  classification?: LiteInputClassification;
  queryPlan?: LiteQueryPlan;
  chunks: LiteRetrievedChunk[];
  judgments: LiteEvidenceJudgment[];
  selectedContext?: LiteSelectedContext;
  synthesis?: LiteSynthesisOutput;
  citationAudit?: LiteCitationAuditOutput;
}

export async function answerLiteClaim(options: LitePipelineOptions): Promise<LiteResponse> {
  const reviewedAt = options.reviewedAt ?? new Date().toISOString();
  const runId = options.runId ?? createLiteRunId();
  let request: LiteClaimRequest;
  try {
    request = liteClaimRequestSchema.parse(options.request);
  } catch {
    return liteErrorResponse({
      status: "invalid_request",
      errorCode: "lite_invalid_request",
      message: "Lite requests require a supported corpus version and a bounded claim or question.",
      retryable: false,
      reviewedAt,
    });
  }

  const state: LitePipelineState = { request, reviewedAt, runId, chunks: [], judgments: [] };
  const deepseekClient = options.deepseekClient ?? createDeepSeekClient();
  const retrieveChunks = options.retrieveChunks ?? retrieveLiteChunks;

  try {
    state.classification = await classifyLiteInput({ request, client: deepseekClient, signal: options.signal });
    if (!state.classification.accepted || state.classification.input_type === "unsupported_request") {
      return liteErrorResponse({
        status: "unsupported_request",
        errorCode: "lite_unsupported_request",
        message:
          state.classification.rejection_reason ??
          "Lite Mode can answer only claims or questions against the curated evidence library.",
        retryable: false,
        requestId: runId,
        corpusVersion: request.corpus_version,
        reviewedAt,
      });
    }

    state.queryPlan = await planLiteQuery({
      request,
      classification: state.classification,
      client: deepseekClient,
      signal: options.signal,
    });

    state.chunks = await retrieveChunks({
      request,
      queryPlan: state.queryPlan,
      reviewedAt,
      deepseekClient,
      signal: options.signal,
    });
    if (state.chunks.length === 0) {
      return insufficientEvidenceResponse(state, [
        "No curated Lite corpus chunks matched the submitted target strongly enough to review.",
      ]);
    }

    state.judgments = await judgeLiteEvidence({
      request,
      classification: state.classification,
      chunks: state.chunks,
      client: deepseekClient,
      signal: options.signal,
    });
    state.selectedContext = selectLiteContext({
      request,
      reviewedAt,
      queryPlan: state.queryPlan,
      chunks: state.chunks,
      judgments: state.judgments,
    });

    if (!hasSufficientDirectEvidence(state.selectedContext)) {
      return insufficientEvidenceResponse(state, [
        "The retrieved chunks are background, weak, or irrelevant rather than direct support or contradiction.",
      ]);
    }

    state.synthesis = await synthesizeLiteAnswer({
      request,
      classification: state.classification,
      selectedContext: state.selectedContext,
      client: deepseekClient,
      signal: options.signal,
    });

    if (state.synthesis.status === "insufficient_evidence") {
      return insufficientEvidenceResponse(state, [
        "The synthesis stage could not answer from the selected chunks without overreaching.",
      ]);
    }

    const audited = await auditAndReviseLiteSynthesis({
      synthesis: state.synthesis,
      selectedContext: state.selectedContext,
      client: deepseekClient,
      signal: options.signal,
    });
    state.citationAudit = audited.audit;

    if (audited.sentences.length === 0 || audited.answerMarkdown.length === 0) {
      return insufficientEvidenceResponse(state, [
        "The citation audit removed every factual sentence because support was missing or too weak.",
      ]);
    }

    return answerResponse(requireAnswerState(state), audited.answerMarkdown, audited.sentences);
  } catch (error) {
    return liteErrorResponse({
      status: classifyPipelineError(error),
      errorCode: errorCode(error),
      message: publicErrorMessage(error),
      retryable: error instanceof LiteDeepSeekError ? error.retryable : false,
      requestId: runId,
      corpusVersion: request.corpus_version,
      reviewedAt,
    });
  }
}

function requireAnswerState(
  state: LitePipelineState,
): LitePipelineState & {
  classification: LiteInputClassification;
  queryPlan: LiteQueryPlan;
  selectedContext: LiteSelectedContext;
  synthesis: LiteSynthesisOutput;
  citationAudit: LiteCitationAuditOutput;
} {
  if (!state.classification || !state.queryPlan || !state.selectedContext || !state.synthesis || !state.citationAudit) {
    throw new Error("Lite answer response is missing a completed pipeline stage");
  }
  return state as LitePipelineState & {
    classification: LiteInputClassification;
    queryPlan: LiteQueryPlan;
    selectedContext: LiteSelectedContext;
    synthesis: LiteSynthesisOutput;
    citationAudit: LiteCitationAuditOutput;
  };
}

export function selectLiteContext(options: {
  request: LiteClaimRequest;
  reviewedAt: string;
  queryPlan: LiteQueryPlan;
  chunks: readonly LiteRetrievedChunk[];
  judgments: readonly LiteEvidenceJudgment[];
}): LiteSelectedContext {
  const judgmentByChunk = new Map(options.judgments.map((judgment) => [judgment.chunk_id, judgment]));
  const ranked = options.chunks
    .map((chunk) => ({
      chunk,
      judgment: judgmentByChunk.get(chunk.chunk_id),
      rank: contextRank(chunk, judgmentByChunk.get(chunk.chunk_id)),
    }))
    .sort((left, right) => right.rank - left.rank || right.chunk.retrieval_scores.combined - left.chunk.retrieval_scores.combined);

  const selected = ranked.slice(0, LITE_MAX_SELECTED_CHUNKS);
  const selectedChunks = selected.map((item) => item.chunk);
  const selectedJudgments = selected
    .map((item) => item.judgment)
    .filter((judgment): judgment is LiteEvidenceJudgment => Boolean(judgment));

  return liteSelectedContextSchema.parse({
    corpus_version: options.request.corpus_version,
    reviewed_at: options.reviewedAt,
    retrieval_strategy: options.queryPlan.retrieval_strategy,
    selected_chunk_ids: selectedChunks.map((chunk) => chunk.chunk_id),
    chunks: selectedChunks,
    judgments: selectedJudgments,
    context_token_budget: LITE_CONTEXT_TOKEN_BUDGET,
    selection_reason:
      "Deterministic Lite selector prioritized direct support and contradiction, then retrieval score and background context.",
    confidence: selected.length ? Math.max(...selected.map((item) => item.rank)) : 0,
    uncertainty: selected.length ? [] : ["No chunks were selected."],
  });
}

export async function auditAndReviseLiteSynthesis(options: {
  synthesis: LiteSynthesisOutput;
  selectedContext: LiteSelectedContext;
  client: Pick<DeepSeekClient, "generateStructured">;
  signal?: AbortSignal;
}): Promise<{
  audit: LiteCitationAuditOutput;
  answerMarkdown: string;
  sentences: LiteCitedSentence[];
}> {
  const chunkIds = new Set(options.selectedContext.chunks.map((chunk) => chunk.chunk_id));
  const deterministicRejected = deterministicCitationRejects(options.synthesis.cited_sentences, chunkIds);
  const assistance =
    deterministicRejected.unknownChunkIds.length || deterministicRejected.missingCitationIndices.length
      ? emptyCitationAssistance(options.synthesis)
      : await assistLiteCitationAudit({
          synthesis: options.synthesis,
          selectedContext: options.selectedContext,
          client: options.client,
          signal: options.signal,
        });

  const modelRejected = modelCitationRejects(options.synthesis.cited_sentences, assistance.output);
  const rejectedByIndex = new Map([...deterministicRejected.rejected, ...modelRejected.rejected]);
  const acceptedSentences = options.synthesis.cited_sentences
    .filter((sentence) => !rejectedByIndex.has(sentence.sentence_index))
    .map((sentence) => ({ ...sentence, support_status: "supported" as const }));
  const auditStatus =
    rejectedByIndex.size === 0
      ? "passed"
      : acceptedSentences.length > 0
        ? "revised"
        : "rejected";

  const audit = liteCitationAuditOutputSchema.parse({
    prompt_version: LITE_CITATION_AUDIT_PROMPT_VERSION,
    model: assistance.model,
    audit_status: auditStatus,
    checked_sentence_count: options.synthesis.cited_sentences.length,
    accepted_sentence_indices: acceptedSentences.map((sentence) => sentence.sentence_index),
    rejected_sentences: [...rejectedByIndex.values()],
    missing_citation_sentence_indices: deterministicRejected.missingCitationIndices,
    unknown_chunk_ids: deterministicRejected.unknownChunkIds,
    confidence: auditStatus === "passed" ? 0.92 : acceptedSentences.length > 0 ? 0.74 : 0.2,
    uncertainty:
      auditStatus === "passed"
        ? []
        : ["Unsupported, partially supported, missing-citation, or unknown-chunk sentences were removed."],
  });

  return {
    audit,
    sentences: acceptedSentences,
    answerMarkdown: acceptedSentences.map((sentence) => sentence.text).join("\n\n").trim(),
  };
}

function hasSufficientDirectEvidence(context: LiteSelectedContext): boolean {
  return context.judgments.some((judgment) => {
    if (!["supports", "contradicts"].includes(judgment.stance) || judgment.confidence < LITE_MIN_DIRECT_JUDGMENT_CONFIDENCE) {
      return false;
    }
    const chunk = context.chunks.find((item) => item.chunk_id === judgment.chunk_id);
    return Boolean(chunk && chunk.retrieval_scores.combined >= LITE_MIN_DIRECT_RETRIEVAL_SCORE);
  });
}

function contextRank(chunk: LiteRetrievedChunk, judgment: LiteEvidenceJudgment | undefined): number {
  const stanceBoost =
    judgment?.stance === "supports" || judgment?.stance === "contradicts"
      ? 0.48
      : judgment?.stance === "background"
        ? 0.16
        : 0;
  const confidence = judgment?.confidence ?? 0;
  return clampScore(chunk.retrieval_scores.combined * 0.42 + confidence * 0.32 + stanceBoost);
}

function deterministicCitationRejects(
  sentences: readonly LiteCitedSentence[],
  chunkIds: Set<string>,
): {
  rejected: Map<number, LiteCitationAuditOutput["rejected_sentences"][number]>;
  missingCitationIndices: number[];
  unknownChunkIds: string[];
} {
  const rejected = new Map<number, LiteCitationAuditOutput["rejected_sentences"][number]>();
  const missingCitationIndices: number[] = [];
  const unknownChunkIds: string[] = [];

  for (const sentence of sentences) {
    if (sentence.citation_ids.length === 0) {
      missingCitationIndices.push(sentence.sentence_index);
      rejected.set(sentence.sentence_index, {
        sentence_index: sentence.sentence_index,
        text: sentence.text,
        citation_ids: [],
        reason: "The factual sentence has no citation ids.",
        support_status: "missing_citation",
      });
      continue;
    }
    const missing = sentence.citation_ids.filter((chunkId) => !chunkIds.has(chunkId));
    if (missing.length > 0) {
      unknownChunkIds.push(...missing);
      rejected.set(sentence.sentence_index, {
        sentence_index: sentence.sentence_index,
        text: sentence.text,
        citation_ids: sentence.citation_ids,
        reason: "The sentence cites a chunk id outside the selected Lite context.",
        support_status: "unknown_chunk",
      });
    }
  }

  return {
    rejected,
    missingCitationIndices,
    unknownChunkIds: Array.from(new Set(unknownChunkIds)),
  };
}

function modelCitationRejects(
  sentences: readonly LiteCitedSentence[],
  assistance: LiteCitationAuditAssistance,
): { rejected: Map<number, LiteCitationAuditOutput["rejected_sentences"][number]> } {
  const sentenceByIndex = new Map(sentences.map((sentence) => [sentence.sentence_index, sentence]));
  const rejected = new Map<number, LiteCitationAuditOutput["rejected_sentences"][number]>();
  for (const support of assistance.sentence_support) {
    if (support.support_status === "supported") {
      continue;
    }
    const sentence = sentenceByIndex.get(support.sentence_index);
    if (!sentence) {
      continue;
    }
    rejected.set(support.sentence_index, {
      sentence_index: sentence.sentence_index,
      text: support.suggested_revision && support.support_status === "partially_supported"
        ? support.suggested_revision
        : sentence.text,
      citation_ids: sentence.citation_ids,
      reason: support.reason,
      support_status: support.support_status === "partially_supported" ? "partial" : "unsupported",
    });
  }
  return { rejected };
}

function emptyCitationAssistance(synthesis: LiteSynthesisOutput): {
  output: LiteCitationAuditAssistance;
  model: LiteModelMetadata;
} {
  return {
    output: { sentence_support: [] },
    model: synthesis.model,
  };
}

function answerResponse(
  state: LitePipelineState & {
    classification: LiteInputClassification;
    queryPlan: LiteQueryPlan;
    selectedContext: LiteSelectedContext;
    synthesis: LiteSynthesisOutput;
    citationAudit: LiteCitationAuditOutput;
  },
  answerMarkdown: string,
  citedSentences: LiteCitedSentence[],
): LiteAnswerResponse {
  return {
    ...baseResponse(state),
    kind: "answer",
    status: "answered",
    audit_status: state.citationAudit.audit_status === "revised" ? "revised" : "passed",
    selected_context: state.selectedContext,
    synthesis: {
      ...state.synthesis,
      answer_markdown: answerMarkdown,
      cited_sentences: citedSentences,
    },
    citation_audit: state.citationAudit,
    answer_markdown: answerMarkdown,
    cited_sentences: citedSentences,
    confidence: Math.min(state.synthesis.confidence, state.citationAudit.confidence),
    uncertainty: [...state.synthesis.uncertainty, ...state.citationAudit.uncertainty].slice(0, 12),
  };
}

function insufficientEvidenceResponse(
  state: LitePipelineState,
  gaps: string[],
): LiteInsufficientEvidenceResponse {
  return {
    ...baseResponse(state),
    kind: "insufficient_evidence",
    status: "insufficient_evidence",
    audit_status: "insufficient_evidence",
    selected_context: state.selectedContext,
    synthesis: state.synthesis,
    citation_audit: state.citationAudit,
    message:
      "The curated Lite evidence library does not contain enough direct evidence to answer this without overreaching.",
    gaps,
    confidence: Math.min(state.synthesis?.confidence ?? 0.35, 0.45),
    uncertainty: [
      "Lite Mode answers only from selected stored corpus chunks.",
      ...(state.synthesis?.uncertainty ?? []),
    ].slice(0, 12),
  };
}

function baseResponse(state: LitePipelineState) {
  const queryPlan = state.queryPlan;
  const retrievalStrategy =
    queryPlan?.retrieval_strategy ??
    state.chunks[0]?.retrieval_strategy ?? {
      name: "lexical_metadata" as const,
      version: LITE_CONTEXT_SELECTOR_VERSION,
      final_top_k: 8,
      filters: { corpus_version: state.request.corpus_version, visibility: "public" },
    };
  const promptVersions = {
    intake: state.classification?.prompt_version ?? LITE_INTAKE_PROMPT_VERSION,
    query_planner: queryPlan?.prompt_version ?? LITE_QUERY_PLANNER_PROMPT_VERSION,
    evidence_judge: state.judgments[0]?.prompt_version ?? LITE_EVIDENCE_JUDGE_PROMPT_VERSION,
    synthesis: state.synthesis?.prompt_version ?? LITE_SYNTHESIS_PROMPT_VERSION,
    citation_audit: state.citationAudit?.prompt_version ?? LITE_CITATION_AUDIT_PROMPT_VERSION,
  };
  const stages = Object.fromEntries(
    [
      ["intake", state.classification?.model],
      ["query_planner", queryPlan?.model],
      ["evidence_judge", state.judgments[0]?.model],
      ["synthesis", state.synthesis?.model],
      ["citation_audit", state.citationAudit?.model],
    ].filter((entry): entry is [string, LiteModelMetadata] => Boolean(entry[1])),
  );

  return {
    run_id: state.runId,
    corpus_version: state.request.corpus_version,
    reviewed_at: state.reviewedAt,
    request: state.request,
    classification: state.classification,
    query_plan: queryPlan,
    retrieval_strategy: retrievalStrategy,
    chunk_ids: state.selectedContext?.selected_chunk_ids ?? state.chunks.map((chunk) => chunk.chunk_id),
    source_labels: Array.from(new Set((state.selectedContext?.chunks ?? state.chunks).map((chunk) => chunk.source_label))).slice(0, 20),
    model_metadata: { provider: "deepseek" as const, stages },
    prompt_versions: promptVersions,
    report_metadata: {
      evidence_reviewed_at: state.reviewedAt,
      methodology_version: LITE_RAG_METHODOLOGY_VERSION,
      workflow_version: LITE_RAG_WORKFLOW_VERSION,
      model_versions: Object.fromEntries(Object.entries(stages).map(([stage, model]) => [stage, model.model])),
      prompt_versions: promptVersions,
      parser_versions: { structured_json: "zod-v4" },
      retrieval_versions: { lite: retrievalStrategy.version, context_selector: LITE_CONTEXT_SELECTOR_VERSION },
      score_roles: {},
      limitations: [
        `Evidence reviewed as of ${state.reviewedAt}. New evidence or corrections may change this assessment.`,
        "Lite Mode uses a curated stored evidence library and is not the complete production verifier.",
      ],
    },
    confidence: state.synthesis?.confidence ?? state.selectedContext?.confidence ?? state.queryPlan?.confidence ?? 0.35,
    uncertainty: state.synthesis?.uncertainty ?? state.selectedContext?.uncertainty ?? [],
  };
}

function liteErrorResponse(options: {
  status: LiteErrorResponse["status"];
  errorCode: string;
  message: string;
  retryable: boolean;
  requestId?: string;
  corpusVersion?: LiteClaimRequest["corpus_version"];
  reviewedAt?: string;
}): LiteErrorResponse {
  return {
    kind: "error",
    status: options.status,
    request_id: options.requestId,
    corpus_version: options.corpusVersion,
    reviewed_at: options.reviewedAt,
    error_code: options.errorCode,
    message: options.message,
    retryable: options.retryable,
    audit_status: "error",
  };
}

function classifyPipelineError(error: unknown): LiteErrorResponse["status"] {
  if (error instanceof LiteDeepSeekError || error instanceof z.ZodError) {
    return "model_error";
  }
  if (error instanceof Error && /supabase|retrieval/i.test(error.name + error.message)) {
    return "retrieval_error";
  }
  return "internal_error";
}

function errorCode(error: unknown): string {
  if (error instanceof LiteDeepSeekError) {
    return error.code;
  }
  if (error instanceof z.ZodError) {
    return "lite_malformed_model_output";
  }
  return "lite_pipeline_error";
}

function publicErrorMessage(error: unknown): string {
  if (error instanceof z.ZodError) {
    return "A Lite model stage returned malformed structured output.";
  }
  if (error instanceof LiteDeepSeekError) {
    return "A server-side DeepSeek Lite stage failed.";
  }
  return "Lite Mode could not complete this request.";
}

function createLiteRunId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `lite_${crypto.randomUUID()}`;
  }
  return `lite_${Date.now().toString(36)}`;
}

function clampScore(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, value));
}
