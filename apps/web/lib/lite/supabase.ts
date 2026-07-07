import { liteRetrievedChunkSchema, type LiteRetrievedChunk } from "./schemas";
import {
  assertLiteServerOnly,
  normalizeHttpBaseUrl,
  readOptionalServerEnv,
  redactForLiteLog,
  requireServerEnv,
  type LiteServerEnv,
} from "./server-config";

assertLiteServerOnly("Lite Supabase client");

export const LITE_SUPABASE_CLIENT_VERSION = "lite-supabase-client-v1";

export interface LiteSupabaseConfig {
  url: string;
  serviceRoleKey: string;
  schema: string;
}

export interface LiteSupabaseLogger {
  info(message: string, metadata?: Record<string, unknown>): void;
  warn(message: string, metadata?: Record<string, unknown>): void;
}

export interface LiteSupabaseRpcOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface LiteVectorMatchRequest {
  queryEmbedding: readonly number[];
  corpusVersion: string;
  matchCount: number;
  minSimilarity?: number;
  documentIds?: readonly string[];
  publisher?: string;
  documentDateStart?: string;
  documentDateEnd?: string;
  includePrivate?: boolean;
  reviewedAt?: string;
}

export interface LiteLexicalMatchRequest {
  queryStrings: readonly string[];
  corpusVersion: string;
  matchCount: number;
  documentIds?: readonly string[];
  publisher?: string;
  documentDateStart?: string;
  documentDateEnd?: string;
  includePrivate?: boolean;
  reviewedAt?: string;
}

export interface LiteRunInsert {
  id: string;
  submitted_text: string;
  input_kind?: string | null;
  corpus_version: string;
  answer_status: "answered" | "insufficient_evidence" | "unsupported_request" | "audit_failed" | "error";
  generated_answer?: string | null;
  generated_answer_metadata?: Record<string, unknown>;
  model_provider: "deepseek";
  model_name?: string | null;
  prompt_versions?: Record<string, unknown>;
  workflow_version?: string | null;
  retrieval_metadata?: Record<string, unknown>;
  citation_audit_status: "pending" | "passed" | "failed" | "revised" | "not_applicable";
  non_sensitive_telemetry?: Record<string, unknown>;
  completed_at?: string | null;
}

export interface LiteRunCitationInsert {
  run_id: string;
  chunk_id: string;
  answer_sentence_index: number;
  chunk_sentence_indexes?: number[];
  support_status: "support" | "contradiction" | "background" | "irrelevant" | "unsupported" | "uncertain";
  audit_status: "pending" | "passed" | "failed" | "revised" | "not_applicable";
  cited_text?: string | null;
  chunk_content_hash_snapshot: string;
  source_citation_label_snapshot: string;
  metadata?: Record<string, unknown>;
}

interface LiteSupabaseRpcErrorBody {
  code?: string;
  message?: string;
  details?: string;
  hint?: string;
}

export class LiteSupabaseError extends Error {
  readonly code: string;
  readonly status: number | undefined;
  readonly retryable: boolean;

  constructor(message: string, options: { code: string; status?: number; retryable?: boolean }) {
    super(message);
    this.name = "LiteSupabaseError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable ?? false;
  }
}

export function loadLiteSupabaseConfig(env: LiteServerEnv = process.env): LiteSupabaseConfig {
  const required = requireServerEnv(
    env,
    ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"],
    "Lite Supabase",
  );

  if (
    required.SUPABASE_URL.startsWith("replace-with-") ||
    required.SUPABASE_SERVICE_ROLE_KEY.startsWith("replace-with-")
  ) {
    throw new LiteSupabaseError("Lite Supabase service-role placeholder cannot be used", {
      code: "supabase_placeholder_secret",
      status: 500,
      retryable: false,
    });
  }

  return {
    url: normalizeHttpBaseUrl(required.SUPABASE_URL, "SUPABASE_URL"),
    serviceRoleKey: required.SUPABASE_SERVICE_ROLE_KEY,
    schema: readOptionalServerEnv(env, "SUPABASE_LITE_SCHEMA") ?? "public",
  };
}

export class LiteSupabaseClient {
  private readonly config: LiteSupabaseConfig;
  private readonly fetchImpl: typeof fetch;
  private readonly logger: LiteSupabaseLogger;

  constructor(options: {
    config?: LiteSupabaseConfig;
    fetchImpl?: typeof fetch;
    logger?: LiteSupabaseLogger;
  } = {}) {
    this.config = options.config ?? loadLiteSupabaseConfig();
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.logger = options.logger ?? console;
  }

  async rpc<T>(
    functionName: string,
    body: Record<string, unknown>,
    options: LiteSupabaseRpcOptions = {},
  ): Promise<T> {
    if (!/^[a-z][a-z0-9_]{0,80}$/.test(functionName)) {
      throw new LiteSupabaseError("Invalid Lite Supabase RPC function name", {
        code: "invalid_rpc_function",
        status: 500,
      });
    }

    const started = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 10_000);
    const signal = options.signal ?? controller.signal;

    try {
      const response = await this.fetchImpl(`${this.config.url}/rest/v1/rpc/${functionName}`, {
        method: "POST",
        headers: this.headers("POST"),
        body: JSON.stringify(body),
        signal,
      });

      const latencyMs = Date.now() - started;
      if (!response.ok) {
        throw await this.mapResponseError(response, latencyMs, functionName);
      }

      this.logger.info("Lite Supabase RPC completed", {
        function_name: functionName,
        schema: this.config.schema,
        latency_ms: latencyMs,
      });
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof LiteSupabaseError) {
        this.logger.warn("Lite Supabase RPC failed", {
          function_name: functionName,
          status: error.status,
          code: error.code,
          retryable: error.retryable,
        });
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        throw new LiteSupabaseError("Lite Supabase request timed out", {
          code: "supabase_timeout",
          retryable: true,
        });
      }
      this.logger.warn("Lite Supabase transport failed", {
        function_name: functionName,
        error: redactForLiteLog(error),
      });
      throw new LiteSupabaseError("Lite Supabase transport failed", {
        code: "supabase_transport_error",
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }
  }

  async matchLiteChunks(request: LiteVectorMatchRequest): Promise<LiteRetrievedChunk[]> {
    const rows = await this.rpc<LiteMatchedChunkRow[]>(
      "match_lite_chunks",
      {
        query_embedding: request.queryEmbedding,
        match_count: request.matchCount,
        min_similarity: request.minSimilarity ?? 0,
        filter_corpus_version: request.corpusVersion,
        filter_document_ids: request.documentIds ? Array.from(request.documentIds) : null,
        filter_publisher: request.publisher ?? null,
        filter_document_date_start: request.documentDateStart ?? null,
        filter_document_date_end: request.documentDateEnd ?? null,
        include_private: request.includePrivate ?? false,
      },
      { timeoutMs: 10_000 },
    );

    const reviewedAt = request.reviewedAt ?? new Date().toISOString();
    return rows.map((row) => mapMatchedChunkRow(row, request.corpusVersion, reviewedAt));
  }

  async searchLiteChunks(request: LiteLexicalMatchRequest): Promise<LiteRetrievedChunk[]> {
    const terms = normalizeLexicalSearchTerms(request.queryStrings).slice(0, 12);
    const hasMetadataFilter = Boolean(
      request.documentIds?.length ||
        request.publisher ||
        request.documentDateStart ||
        request.documentDateEnd ||
        request.includePrivate,
    );
    if (terms.length === 0 && !hasMetadataFilter) {
      return [];
    }

    const params = new URLSearchParams();
    params.set(
      "select",
      [
        "id",
        "document_id",
        "corpus_version",
        "chunk_text",
        "heading_path",
        "page_number",
        "section_label",
        "paragraph_index",
        "content_hash",
        "source_citation_label",
        "metadata",
        "lite_documents!inner(title,source_url,publisher,document_date,visibility)",
      ].join(","),
    );
    params.set("corpus_version", `eq.${request.corpusVersion}`);
    params.set("limit", String(Math.max(1, Math.min(50, request.matchCount))));
    params.set("order", "chunk_index.asc");
    params.set("lite_documents.visibility", request.includePrivate ? "not.eq.disabled" : "eq.public");

    if (request.documentIds?.length) {
      params.set("document_id", `in.(${request.documentIds.map(escapePostgrestListValue).join(",")})`);
    }
    if (request.publisher) {
      params.set("lite_documents.publisher", `eq.${request.publisher}`);
    }
    if (request.documentDateStart) {
      params.set("lite_documents.document_date", `gte.${request.documentDateStart}`);
    }
    if (request.documentDateEnd) {
      params.append("lite_documents.document_date", `lte.${request.documentDateEnd}`);
    }
    if (terms.length > 0) {
      params.set(
        "or",
        `(${terms
          .flatMap((term) => [
            `chunk_text.ilike.*${escapePostgrestPattern(term)}*`,
            `source_citation_label.ilike.*${escapePostgrestPattern(term)}*`,
          ])
          .join(",")})`,
      );
    }

    const response = await this.restGet<LiteLexicalChunkRow[]>(`lite_chunks?${params.toString()}`, {
      timeoutMs: 10_000,
    });
    const reviewedAt = request.reviewedAt ?? new Date().toISOString();
    return response.map((row) => mapLexicalChunkRow(row, request.corpusVersion, reviewedAt));
  }

  async insertLiteRun(row: LiteRunInsert, options: LiteSupabaseRpcOptions = {}): Promise<void> {
    await this.restPost("lite_runs", row, options);
  }

  async insertLiteRunCitations(
    rows: readonly LiteRunCitationInsert[],
    options: LiteSupabaseRpcOptions = {},
  ): Promise<void> {
    if (rows.length === 0) {
      return;
    }
    await this.restPost("lite_run_citations", rows, options);
  }

  private headers(method: "GET" | "POST"): HeadersInit {
    const profileHeader = method === "GET" ? "Accept-Profile" : "Content-Profile";
    return {
      Authorization: `Bearer ${this.config.serviceRoleKey}`,
      apikey: this.config.serviceRoleKey,
      "Content-Type": "application/json",
      Accept: "application/json",
      [profileHeader]: this.config.schema,
    };
  }

  private async mapResponseError(
    response: Response,
    latencyMs: number,
    functionName: string,
  ): Promise<LiteSupabaseError> {
    const status = response.status;
    let body: LiteSupabaseRpcErrorBody = {};
    try {
      body = (await response.json()) as LiteSupabaseRpcErrorBody;
    } catch {
      body = {};
    }

    this.logger.warn("Lite Supabase rejected a request", {
      function_name: functionName,
      status,
      latency_ms: latencyMs,
      provider_code: body.code,
      provider_message: "[redacted]",
    });

    return new LiteSupabaseError("Lite Supabase request was rejected", {
      code: mapSupabaseStatus(status, body.code),
      status,
      retryable: status === 408 || status === 429 || status >= 500,
    });
  }

  private async restGet<T>(path: string, options: LiteSupabaseRpcOptions = {}): Promise<T> {
    const started = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 10_000);
    const signal = options.signal ?? controller.signal;

    try {
      const response = await this.fetchImpl(`${this.config.url}/rest/v1/${path}`, {
        method: "GET",
        headers: this.headers("GET"),
        signal,
      });
      const latencyMs = Date.now() - started;
      if (!response.ok) {
        throw await this.mapResponseError(response, latencyMs, "rest_get_lite_chunks");
      }
      this.logger.info("Lite Supabase REST read completed", {
        resource: "lite_chunks",
        schema: this.config.schema,
        latency_ms: latencyMs,
      });
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof LiteSupabaseError) {
        this.logger.warn("Lite Supabase REST read failed", {
          resource: "lite_chunks",
          status: error.status,
          code: error.code,
          retryable: error.retryable,
        });
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        throw new LiteSupabaseError("Lite Supabase request timed out", {
          code: "supabase_timeout",
          retryable: true,
        });
      }
      this.logger.warn("Lite Supabase REST transport failed", {
        resource: "lite_chunks",
        error: redactForLiteLog(error),
      });
      throw new LiteSupabaseError("Lite Supabase transport failed", {
        code: "supabase_transport_error",
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }
  }

  private async restPost<T>(
    resource: "lite_runs" | "lite_run_citations",
    body: object | readonly object[],
    options: LiteSupabaseRpcOptions = {},
  ): Promise<T | undefined> {
    const started = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 10_000);
    const signal = options.signal ?? controller.signal;

    try {
      const response = await this.fetchImpl(`${this.config.url}/rest/v1/${resource}`, {
        method: "POST",
        headers: {
          ...this.headers("POST"),
          Prefer: "return=minimal",
        },
        body: JSON.stringify(body),
        signal,
      });
      const latencyMs = Date.now() - started;
      if (!response.ok) {
        throw await this.mapResponseError(response, latencyMs, `rest_post_${resource}`);
      }
      this.logger.info("Lite Supabase REST write completed", {
        resource,
        schema: this.config.schema,
        latency_ms: latencyMs,
      });
      if (response.status === 204) {
        return undefined;
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof LiteSupabaseError) {
        this.logger.warn("Lite Supabase REST write failed", {
          resource,
          status: error.status,
          code: error.code,
          retryable: error.retryable,
        });
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        throw new LiteSupabaseError("Lite Supabase request timed out", {
          code: "supabase_timeout",
          retryable: true,
        });
      }
      this.logger.warn("Lite Supabase REST write transport failed", {
        resource,
        error: redactForLiteLog(error),
      });
      throw new LiteSupabaseError("Lite Supabase transport failed", {
        code: "supabase_transport_error",
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
    }
  }
}

export interface LiteMatchedChunkRow {
  chunk_id: string;
  document_id: string;
  title: string;
  source_url?: string | null;
  publisher?: string | null;
  document_date?: string | null;
  corpus_version: string;
  chunk_text: string;
  heading_path?: string[] | null;
  page_number?: number | null;
  section_label?: string | null;
  paragraph_index?: number | null;
  content_hash: string;
  source_citation_label: string;
  similarity?: number | null;
  metadata?: Record<string, unknown> | null;
}

interface LiteLexicalChunkRow {
  id: string;
  document_id: string;
  corpus_version: string;
  chunk_text: string;
  heading_path?: string[] | null;
  page_number?: number | null;
  section_label?: string | null;
  paragraph_index?: number | null;
  content_hash: string;
  source_citation_label: string;
  metadata?: Record<string, unknown> | null;
  lite_documents?:
    | LiteLexicalDocumentRow
    | LiteLexicalDocumentRow[]
    | null;
}

interface LiteLexicalDocumentRow {
  title?: string | null;
  source_url?: string | null;
  publisher?: string | null;
  document_date?: string | null;
  visibility?: string | null;
}

export function mapMatchedChunkRow(
  row: LiteMatchedChunkRow,
  expectedCorpusVersion: string,
  reviewedAt: string,
): LiteRetrievedChunk {
  const semanticScore = clampScore(row.similarity ?? 0);
  return liteRetrievedChunkSchema.parse({
    corpus_version: row.corpus_version || expectedCorpusVersion,
    chunk_id: row.chunk_id,
    document_id: row.document_id,
    source_label: row.source_citation_label,
    source_title: row.title,
    source_url: row.source_url ?? undefined,
    publisher: row.publisher ?? undefined,
    document_date: row.document_date ?? undefined,
    reviewed_at: reviewedAt,
    chunk_text: row.chunk_text,
    heading_path: row.heading_path?.join(" > ") || undefined,
    page_or_position: row.section_label ?? (row.page_number ? `page ${row.page_number}` : undefined),
    paragraph_index: row.paragraph_index ?? undefined,
    content_hash: row.content_hash,
    retrieval_scores: {
      semantic: semanticScore,
      combined: semanticScore,
    },
    retrieval_strategy: {
      name: "hybrid_pgvector_lexical",
      version: LITE_SUPABASE_CLIENT_VERSION,
      semantic_top_k: 8,
      final_top_k: 8,
      min_similarity: 0,
      filters: { corpus_version: expectedCorpusVersion },
    },
    metadata: row.metadata ?? {},
  });
}

function mapLexicalChunkRow(
  row: LiteLexicalChunkRow,
  expectedCorpusVersion: string,
  reviewedAt: string,
): LiteRetrievedChunk {
  const document = Array.isArray(row.lite_documents) ? row.lite_documents[0] : row.lite_documents;
  return liteRetrievedChunkSchema.parse({
    corpus_version: row.corpus_version || expectedCorpusVersion,
    chunk_id: row.id,
    document_id: row.document_id,
    source_label: row.source_citation_label,
    source_title: document?.title ?? "Lite source",
    source_url: document?.source_url ?? undefined,
    publisher: document?.publisher ?? undefined,
    document_date: document?.document_date ?? undefined,
    reviewed_at: reviewedAt,
    chunk_text: row.chunk_text,
    heading_path: row.heading_path?.join(" > ") || undefined,
    page_or_position: row.section_label ?? (row.page_number ? `page ${row.page_number}` : undefined),
    paragraph_index: row.paragraph_index ?? undefined,
    content_hash: row.content_hash,
    retrieval_scores: {
      lexical: 0,
      combined: 0,
      low_confidence: true,
    },
    retrieval_strategy: {
      name: "lexical_metadata",
      version: LITE_SUPABASE_CLIENT_VERSION,
      lexical_top_k: 8,
      final_top_k: 8,
      filters: { corpus_version: expectedCorpusVersion, visibility: document?.visibility ?? "public" },
    },
    metadata: row.metadata ?? {},
  });
}

function clampScore(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, value));
}

function normalizeLexicalSearchTerms(queryStrings: readonly string[]): string[] {
  const terms = queryStrings
    .flatMap((query) => query.toLowerCase().match(/[a-z0-9][a-z0-9.-]{1,79}/g) ?? [])
    .filter((term) => !["and", "the", "that", "with", "from", "this", "into", "over"].includes(term));
  return Array.from(new Set(terms));
}

function escapePostgrestPattern(value: string): string {
  return value.replace(/[*(),]/g, " ");
}

function escapePostgrestListValue(value: string): string {
  return `"${value.replace(/"/g, "\"\"")}"`;
}

function mapSupabaseStatus(status: number, providerCode: string | undefined): string {
  if (status === 401 || status === 403) {
    return "supabase_authentication_error";
  }
  if (status === 408) {
    return "supabase_timeout";
  }
  if (status === 429) {
    return "supabase_rate_limited";
  }
  if (status >= 500) {
    return "supabase_unavailable";
  }
  return providerCode ? `supabase_${providerCode}` : "supabase_rejected";
}

export function createLiteSupabaseClient(options: ConstructorParameters<typeof LiteSupabaseClient>[0] = {}) {
  return new LiteSupabaseClient(options);
}
