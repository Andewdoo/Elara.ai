import {
  type LiteAnswerResponse,
  type LiteCitedSentence,
  type LiteInsufficientEvidenceResponse,
  type LiteResponse,
  type LiteRetrievedChunk,
} from "./schemas";
import { assertLiteServerOnly, readOptionalServerEnv, redactForLiteLog, type LiteServerEnv } from "./server-config";
import {
  createLiteSupabaseClient,
  type LiteRunCitationInsert,
  type LiteRunInsert,
  type LiteSupabaseClient,
} from "./supabase";

assertLiteServerOnly("Lite run persistence");

export const LITE_RUN_PERSISTENCE_VERSION = "lite-run-persistence-v1";

export class LiteRunPersistenceError extends Error {
  readonly code = "lite_run_persistence_error";

  constructor(message = "Lite run persistence failed") {
    super(message);
    this.name = "LiteRunPersistenceError";
  }
}

export interface LitePersistRunOptions {
  env?: LiteServerEnv;
  supabaseClient?: Pick<LiteSupabaseClient, "insertLiteRun" | "insertLiteRunCitations">;
  logger?: Pick<Console, "warn">;
  signal?: AbortSignal;
}

export async function persistLiteRunIfConfigured(
  response: LiteResponse,
  options: LitePersistRunOptions = {},
): Promise<"persisted" | "skipped" | "not_persistable"> {
  if (response.kind === "error") {
    return "not_persistable";
  }
  if (!isLiteRunPersistenceConfigured(options.env)) {
    return "skipped";
  }

  const client = options.supabaseClient ?? createLiteSupabaseClient();
  try {
    await client.insertLiteRun(toRunInsert(response), { signal: options.signal });
    await client.insertLiteRunCitations(toCitationInserts(response), { signal: options.signal });
    return "persisted";
  } catch (error) {
    options.logger?.warn("Lite run persistence failed", { error: redactForLiteLog(error) });
    throw new LiteRunPersistenceError();
  }
}

export function isLiteRunPersistenceConfigured(env: LiteServerEnv = process.env): boolean {
  const url = readOptionalServerEnv(env, "SUPABASE_URL");
  const serviceRoleKey = readOptionalServerEnv(env, "SUPABASE_SERVICE_ROLE_KEY");
  return Boolean(
    url &&
      serviceRoleKey &&
      !url.startsWith("replace-with-") &&
      !serviceRoleKey.startsWith("replace-with-"),
  );
}

function toRunInsert(response: LiteAnswerResponse | LiteInsufficientEvidenceResponse): LiteRunInsert {
  const firstModel = Object.values(response.model_metadata.stages)[0];
  return {
    id: response.run_id,
    submitted_text: response.request.input,
    input_kind: response.classification?.input_type ?? response.request.input_type_hint ?? null,
    corpus_version: response.corpus_version,
    answer_status: response.kind === "answer" ? "answered" : "insufficient_evidence",
    generated_answer: response.kind === "answer" ? response.answer_markdown : response.message,
    generated_answer_metadata: {
      response_kind: response.kind,
      confidence: response.confidence,
      uncertainty: response.uncertainty,
      source_labels: response.source_labels,
      chunk_count: response.chunk_ids.length,
      persistence_version: LITE_RUN_PERSISTENCE_VERSION,
    },
    model_provider: "deepseek",
    model_name: firstModel?.model ?? null,
    prompt_versions: response.prompt_versions,
    workflow_version: response.report_metadata.workflow_version,
    retrieval_metadata: {
      retrieval_strategy: response.retrieval_strategy,
      chunk_ids: response.chunk_ids,
      source_labels: response.source_labels,
      corpus_version: response.corpus_version,
    },
    citation_audit_status: mapAuditStatus(response.audit_status),
    non_sensitive_telemetry: {
      client_trace_id: response.request.client_trace_id,
      status: response.status,
      model_stage_count: Object.keys(response.model_metadata.stages).length,
    },
    completed_at: response.reviewed_at,
  };
}

function toCitationInserts(response: LiteAnswerResponse | LiteInsufficientEvidenceResponse): LiteRunCitationInsert[] {
  if (response.kind !== "answer") {
    return [];
  }

  const chunkById = new Map(response.selected_context.chunks.map((chunk) => [chunk.chunk_id, chunk]));
  const judgmentByChunkId = new Map(response.selected_context.judgments.map((judgment) => [judgment.chunk_id, judgment]));
  const rows: LiteRunCitationInsert[] = [];

  for (const sentence of response.cited_sentences) {
    for (const citationId of sentence.citation_ids) {
      const chunk = chunkById.get(citationId);
      if (!chunk || !isUuid(citationId)) {
        continue;
      }
      rows.push(toCitationInsert(response, sentence, chunk, judgmentByChunkId.get(citationId)?.stance));
    }
  }

  return rows;
}

function toCitationInsert(
  response: LiteAnswerResponse,
  sentence: LiteCitedSentence,
  chunk: LiteRetrievedChunk,
  stance: string | undefined,
): LiteRunCitationInsert {
  return {
    run_id: response.run_id,
    chunk_id: chunk.chunk_id,
    answer_sentence_index: sentence.sentence_index,
    chunk_sentence_indexes: [],
    support_status: mapSupportStatus(stance, sentence.support_status),
    audit_status: mapAuditStatus(response.audit_status),
    cited_text: sentence.text,
    chunk_content_hash_snapshot: chunk.content_hash,
    source_citation_label_snapshot: chunk.source_label,
    metadata: {
      source_title: chunk.source_title,
      source_url: chunk.source_url,
      publisher: chunk.publisher,
      document_date: chunk.document_date,
      heading_path: chunk.heading_path,
      page_or_position: chunk.page_or_position,
      confidence: sentence.confidence,
    },
  };
}

function mapAuditStatus(status: LiteResponse["audit_status"]): LiteRunInsert["citation_audit_status"] {
  if (status === "passed") {
    return "passed";
  }
  if (status === "revised") {
    return "revised";
  }
  if (status === "rejected" || status === "error") {
    return "failed";
  }
  if (status === "insufficient_evidence" || status === "not_run") {
    return "not_applicable";
  }
  return "pending";
}

function mapSupportStatus(
  stance: string | undefined,
  sentenceSupport: LiteCitedSentence["support_status"],
): LiteRunCitationInsert["support_status"] {
  if (sentenceSupport === "unsupported" || sentenceSupport === "missing_citation") {
    return "unsupported";
  }
  if (sentenceSupport === "partially_supported") {
    return "uncertain";
  }
  if (stance === "supports") {
    return "support";
  }
  if (stance === "contradicts") {
    return "contradiction";
  }
  if (stance === "background" || stance === "irrelevant") {
    return stance;
  }
  return "uncertain";
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
