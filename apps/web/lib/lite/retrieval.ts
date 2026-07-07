import { createDeepSeekClient, extractLiteLexicalTerms, type DeepSeekClient } from "./deepseek";
import {
  liteClaimRequestSchema,
  liteRetrievedChunkSchema,
  type LiteClaimRequest,
  type LiteQueryPlan,
  type LiteRetrievedChunk,
} from "./schemas";
import { assertLiteServerOnly } from "./server-config";
import {
  createLiteSupabaseClient,
  type LiteLexicalMatchRequest,
  type LiteSupabaseClient,
  type LiteVectorMatchRequest,
} from "./supabase";

assertLiteServerOnly("Lite retrieval");

export const LITE_RETRIEVAL_VERSION = "lite-retrieval-v1";

export interface LiteRetrievalFilters {
  corpusVersion: string;
  documentIds?: readonly string[];
  publisher?: string;
  documentDateStart?: string;
  documentDateEnd?: string;
  includePrivate?: boolean;
}

export interface LiteRetrieveChunksOptions {
  request: LiteClaimRequest | unknown;
  queryPlan?: Pick<LiteQueryPlan, "embedding_text" | "lexical_terms" | "entity_filters" | "query_variants">;
  filters?: Partial<LiteRetrievalFilters>;
  finalTopK?: number;
  semanticTopK?: number;
  lexicalTopK?: number;
  minSimilarity?: number;
  reviewedAt?: string;
  deepseekClient?: Pick<DeepSeekClient, "embeddingAvailable" | "generateEmbeddings" | "createLexicalMetadataFallback">;
  supabaseClient?: Pick<LiteSupabaseClient, "matchLiteChunks" | "searchLiteChunks">;
  signal?: AbortSignal;
}

interface RankedCandidate {
  chunk: LiteRetrievedChunk;
  semantic: number | undefined;
  lexical: number;
  metadata: number;
  combined: number;
  lowConfidence: boolean;
  exactSignals: ExactSignals;
}

interface ExactSignals {
  quotes: string[];
  names: string[];
  numbers: string[];
  dates: string[];
  identifiers: string[];
}

export async function retrieveLiteChunks(options: LiteRetrieveChunksOptions): Promise<LiteRetrievedChunk[]> {
  const request = liteClaimRequestSchema.parse(options.request);
  const finalTopK = boundInteger(options.finalTopK ?? 8, 1, 20);
  const semanticTopK = boundInteger(options.semanticTopK ?? 24, finalTopK, 50);
  const lexicalTopK = boundInteger(options.lexicalTopK ?? 24, finalTopK, 50);
  const minSimilarity = clampScore(options.minSimilarity ?? 0.35);
  const reviewedAt = options.reviewedAt ?? new Date().toISOString();
  const filters = resolveFilters(request, options.filters);
  const queryStrings = buildLiteRetrievalQueries(request, options.queryPlan);
  const lexicalTerms = buildLexicalTerms(request, options.queryPlan, queryStrings);
  const exactSignals = extractExactSignals(request.input);
  const strategyBase = {
    name: "hybrid_pgvector_lexical" as const,
    version: LITE_RETRIEVAL_VERSION,
    semantic_top_k: semanticTopK,
    lexical_top_k: lexicalTopK,
    final_top_k: finalTopK,
    min_similarity: minSimilarity,
    filters: {
      corpus_version: filters.corpusVersion,
      visibility: filters.includePrivate ? "public_private" : "public",
      ...(filters.documentIds?.length ? { document_ids: [...filters.documentIds] } : {}),
      ...(filters.publisher ? { publisher: filters.publisher } : {}),
      ...(filters.documentDateStart ? { document_date_start: filters.documentDateStart } : {}),
      ...(filters.documentDateEnd ? { document_date_end: filters.documentDateEnd } : {}),
    },
  };

  const supabaseClient = options.supabaseClient ?? createLiteSupabaseClient();
  const deepseekClient = options.deepseekClient ?? createDeepSeekClient();
  const vectorCandidates: LiteRetrievedChunk[] = [];

  if (deepseekClient.embeddingAvailable) {
    const embeddingText = queryStrings[0] ?? request.input;
    const embedding = await deepseekClient.generateEmbeddings([embeddingText], { signal: options.signal });
    vectorCandidates.push(
      ...(await supabaseClient.matchLiteChunks(
        vectorRequest(embedding.vectors[0], filters, semanticTopK, minSimilarity, reviewedAt),
      )),
    );
  } else {
    deepseekClient.createLexicalMetadataFallback(queryStrings);
  }

  const lexicalCandidates = await supabaseClient.searchLiteChunks(
    lexicalRequest(queryStrings, filters, lexicalTopK, reviewedAt),
  );
  const ranked = [...vectorCandidates, ...lexicalCandidates]
    .filter((chunk) => chunk.corpus_version === filters.corpusVersion)
    .map((chunk) => rankCandidate(chunk, {
      lexicalTerms,
      queryStrings,
      exactSignals,
      entityFilters: options.queryPlan?.entity_filters ?? {},
      strategy: strategyBase,
    }))
    .sort((left, right) => right.combined - left.combined || tieBreak(right.chunk, left.chunk));

  return dedupeRankedCandidates(ranked)
    .slice(0, finalTopK)
    .map((candidate) => finalizeCandidate(candidate, strategyBase));
}

export function buildLiteRetrievalQueries(
  request: LiteClaimRequest,
  queryPlan?: Pick<LiteQueryPlan, "embedding_text" | "lexical_terms" | "query_variants">,
): string[] {
  const values = [
    queryPlan?.embedding_text,
    ...(queryPlan?.query_variants ?? []),
    request.input,
    exactQueryFragment(request.input),
    ...(queryPlan?.lexical_terms?.length ? [queryPlan.lexical_terms.join(" ")] : []),
  ];
  return Array.from(
    new Set(
      values
        .map((value) => value?.replace(/\s+/g, " ").trim())
        .filter((value): value is string => Boolean(value && value.length >= 2))
        .map((value) => value.slice(0, 1600)),
    ),
  ).slice(0, 8);
}

function resolveFilters(request: LiteClaimRequest, filters: Partial<LiteRetrievalFilters> = {}): LiteRetrievalFilters {
  return {
    corpusVersion: filters.corpusVersion ?? request.corpus_version,
    documentIds: filters.documentIds?.filter(Boolean),
    publisher: filters.publisher?.trim() || undefined,
    documentDateStart: filters.documentDateStart,
    documentDateEnd: filters.documentDateEnd,
    includePrivate: filters.includePrivate ?? false,
  };
}

function vectorRequest(
  queryEmbedding: readonly number[],
  filters: LiteRetrievalFilters,
  matchCount: number,
  minSimilarity: number,
  reviewedAt: string,
): LiteVectorMatchRequest {
  return {
    queryEmbedding,
    corpusVersion: filters.corpusVersion,
    matchCount,
    minSimilarity,
    documentIds: filters.documentIds,
    publisher: filters.publisher,
    documentDateStart: filters.documentDateStart,
    documentDateEnd: filters.documentDateEnd,
    includePrivate: filters.includePrivate,
    reviewedAt,
  };
}

function lexicalRequest(
  queryStrings: readonly string[],
  filters: LiteRetrievalFilters,
  matchCount: number,
  reviewedAt: string,
): LiteLexicalMatchRequest {
  return {
    queryStrings,
    corpusVersion: filters.corpusVersion,
    matchCount,
    documentIds: filters.documentIds,
    publisher: filters.publisher,
    documentDateStart: filters.documentDateStart,
    documentDateEnd: filters.documentDateEnd,
    includePrivate: filters.includePrivate,
    reviewedAt,
  };
}

function buildLexicalTerms(
  request: LiteClaimRequest,
  queryPlan: Pick<LiteQueryPlan, "lexical_terms"> | undefined,
  queryStrings: readonly string[],
): string[] {
  const terms = [
    ...(queryPlan?.lexical_terms ?? []),
    ...extractLiteLexicalTerms(queryStrings.join(" "), 40),
    ...extractLiteLexicalTerms(request.input, 40),
  ];
  return Array.from(new Set(terms.map((term) => term.toLowerCase().trim()).filter(Boolean))).slice(0, 50);
}

function rankCandidate(
  chunk: LiteRetrievedChunk,
  context: {
    lexicalTerms: readonly string[];
    queryStrings: readonly string[];
    exactSignals: ExactSignals;
    entityFilters: Record<string, unknown>;
    strategy: LiteRetrievedChunk["retrieval_strategy"];
  },
): RankedCandidate {
  const semantic = chunk.retrieval_scores.semantic;
  const lexical = lexicalScore(chunk, context.lexicalTerms, context.queryStrings, context.exactSignals);
  const metadata = metadataScore(chunk, context.entityFilters);
  const exactBoost = exactSignalBoost(chunk, context.exactSignals);
  const hasSemantic = typeof semantic === "number";
  const combined = clampScore(
    hasSemantic
      ? semantic * 0.48 + lexical * 0.36 + metadata * 0.08 + exactBoost
      : lexical * 0.76 + metadata * 0.12 + exactBoost,
  );
  const lowConfidence =
    combined < 0.45 ||
    (lexical < 0.18 && exactBoost === 0 && (!hasSemantic || semantic < (context.strategy.min_similarity ?? 0.35)));

  return {
    chunk,
    semantic,
    lexical,
    metadata,
    combined,
    lowConfidence,
    exactSignals: context.exactSignals,
  };
}

function lexicalScore(
  chunk: LiteRetrievedChunk,
  lexicalTerms: readonly string[],
  queryStrings: readonly string[],
  exactSignals: ExactSignals,
): number {
  const haystack = searchableText(chunk);
  const matchedTerms = lexicalTerms.filter((term) => haystack.includes(term.toLowerCase()));
  const termScore = lexicalTerms.length ? matchedTerms.length / lexicalTerms.length : 0;
  const phraseScore = queryStrings.some((query) => query.length >= 12 && haystack.includes(query.toLowerCase()))
    ? 0.22
    : 0;
  const signalCount = [
    ...exactSignals.quotes,
    ...exactSignals.numbers,
    ...exactSignals.dates,
    ...exactSignals.identifiers,
    ...exactSignals.names,
  ].filter((signal) => haystack.includes(signal.toLowerCase())).length;
  const signalScore = Math.min(0.36, signalCount * 0.08);
  return clampScore(termScore * 0.78 + phraseScore + signalScore);
}

function metadataScore(chunk: LiteRetrievedChunk, entityFilters: Record<string, unknown>): number {
  const filters = Object.entries(entityFilters).filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (filters.length === 0) {
    return 1;
  }
  const text = searchableText(chunk);
  const matches = filters.filter(([key, value]) => {
    const expected = Array.isArray(value) ? value.map(String) : [String(value)];
    const metadataValue = chunk.metadata[key];
    return expected.some((item) => {
      const normalized = item.toLowerCase();
      return (
        text.includes(normalized) ||
        String(metadataValue ?? "").toLowerCase().includes(normalized) ||
        String(chunk.publisher ?? "").toLowerCase().includes(normalized) ||
        String(chunk.document_date ?? "").toLowerCase().includes(normalized)
      );
    });
  });
  return matches.length / filters.length;
}

function exactSignalBoost(chunk: LiteRetrievedChunk, signals: ExactSignals): number {
  const haystack = searchableText(chunk);
  const groups = [
    { values: signals.quotes, weight: 0.16 },
    { values: signals.numbers, weight: 0.08 },
    { values: signals.dates, weight: 0.08 },
    { values: signals.identifiers, weight: 0.08 },
    { values: signals.names, weight: 0.05 },
  ];
  return Math.min(
    0.28,
    groups.reduce(
      (total, group) =>
        total + Math.min(group.weight, group.values.filter((value) => haystack.includes(value.toLowerCase())).length * group.weight),
      0,
    ),
  );
}

function finalizeCandidate(
  candidate: RankedCandidate,
  strategy: LiteRetrievedChunk["retrieval_strategy"],
): LiteRetrievedChunk {
  return liteRetrievedChunkSchema.parse({
    ...candidate.chunk,
    retrieval_scores: {
      semantic: candidate.semantic,
      lexical: Number(candidate.lexical.toFixed(4)),
      metadata: Number(candidate.metadata.toFixed(4)),
      combined: Number(candidate.combined.toFixed(4)),
      low_confidence: candidate.lowConfidence,
    },
    retrieval_strategy: strategy,
    metadata: {
      ...candidate.chunk.metadata,
      lite_retrieval_version: LITE_RETRIEVAL_VERSION,
      low_confidence_retrieval: candidate.lowConfidence,
      matched_exact_signals: candidate.exactSignals,
    },
  });
}

function dedupeRankedCandidates(candidates: readonly RankedCandidate[]): RankedCandidate[] {
  const selected: RankedCandidate[] = [];
  const contentHashes = new Set<string>();
  for (const candidate of candidates) {
    if (contentHashes.has(candidate.chunk.content_hash)) {
      continue;
    }
    if (selected.some((existing) => isNearDuplicate(existing.chunk.chunk_text, candidate.chunk.chunk_text))) {
      continue;
    }
    contentHashes.add(candidate.chunk.content_hash);
    selected.push(candidate);
  }
  return selected;
}

function isNearDuplicate(left: string, right: string): boolean {
  const leftTerms = new Set(extractLiteLexicalTerms(left, 120));
  const rightTerms = new Set(extractLiteLexicalTerms(right, 120));
  if (leftTerms.size === 0 || rightTerms.size === 0) {
    return normalizedText(left) === normalizedText(right);
  }
  const intersection = [...leftTerms].filter((term) => rightTerms.has(term)).length;
  const union = new Set([...leftTerms, ...rightTerms]).size;
  return intersection / union >= 0.92;
}

function extractExactSignals(input: string): ExactSignals {
  return {
    quotes: extractQuotedPhrases(input),
    names: extractNames(input),
    numbers: uniqueMatches(input, /\b\d+(?:[,.]\d+)*(?:\.\d+)?(?:%|[a-zA-Z]+)?\b/g),
    dates: uniqueMatches(
      input,
      /\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4})\b/gi,
    ),
    identifiers: uniqueMatches(input, /\b[A-Z]{2,}[-_ ]?\d{2,}[A-Z0-9-]*\b/g),
  };
}

function extractQuotedPhrases(input: string): string[] {
  const phrases: string[] = [];
  for (const match of input.matchAll(/"([^"]{4,240})"|'([^']{4,240})'/g)) {
    phrases.push((match[1] ?? match[2]).replace(/\s+/g, " ").trim());
  }
  return Array.from(new Set(phrases));
}

function extractNames(input: string): string[] {
  const stop = new Set(["The", "This", "That", "When", "Where", "What", "Why", "How", "Lite", "Full"]);
  return Array.from(
    new Set(
      (input.match(/\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b/g) ?? [])
        .map((name) => name.trim())
        .filter((name) => !stop.has(name) && name.length >= 4),
    ),
  ).slice(0, 16);
}

function uniqueMatches(input: string, pattern: RegExp): string[] {
  return Array.from(new Set((input.match(pattern) ?? []).map((value) => value.trim()))).slice(0, 24);
}

function exactQueryFragment(input: string): string {
  const signals = extractExactSignals(input);
  return [...signals.quotes, ...signals.names, ...signals.numbers, ...signals.dates, ...signals.identifiers].join(" ");
}

function searchableText(chunk: LiteRetrievedChunk): string {
  return normalizedText(
    [
      chunk.chunk_text,
      chunk.source_label,
      chunk.source_title,
      chunk.publisher,
      chunk.document_date,
      chunk.heading_path,
      chunk.page_or_position,
      JSON.stringify(chunk.metadata),
    ]
      .filter(Boolean)
      .join(" "),
  );
}

function normalizedText(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function tieBreak(left: LiteRetrievedChunk, right: LiteRetrievedChunk): number {
  return String(left.document_date ?? "").localeCompare(String(right.document_date ?? "")) ||
    right.source_label.localeCompare(left.source_label);
}

function boundInteger(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function clampScore(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, value));
}
