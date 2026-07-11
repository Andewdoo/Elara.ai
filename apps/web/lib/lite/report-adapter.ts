import type { VerificationRun } from "@/hooks/use-run-events";
import type { EvidenceStance, ReportCitation, ReportRecord, ReportWorkspaceData, SourceGraphRecord, SourcePassage, SourceRecord } from "@/lib/report-types";
import type { LiteAnswerResponse, LiteEvidenceJudgment, LiteInsufficientEvidenceResponse, LiteRetrievedChunk, LiteResponse } from "./schemas";

type AdaptableLiteResponse = LiteAnswerResponse | LiteInsufficientEvidenceResponse;

const LITE_SCOPE = "Evidence came from the curated Lite evidence library, not live web retrieval or the complete production verifier.";

export function liteResponseToReportWorkspace(response: AdaptableLiteResponse): ReportWorkspaceData {
  const chunks = response.selected_context?.chunks ?? [];
  const judgments = response.selected_context?.judgments ?? [];
  const citations = response.kind === "answer" ? response.cited_sentences : [];
  const sources = toSources(chunks, citations);
  const evidence = chunks.map((chunk, index) => toEvidence(chunk, judgments.find((judgment) => judgment.chunk_id === chunk.chunk_id), index));
  const reportSentences = citations.map((sentence) => ({
    id: `lite-sentence-${sentence.sentence_index}`,
    report_section: "summary",
    sentence_text: sentence.text,
    passage_id: sentence.citation_ids[0],
    audit_status: sentence.support_status,
    audit_note: `Lite citation audit; source labels: ${sentence.source_labels.join(", ")}`,
  }));
  const uncertainty = [...response.uncertainty, ...(response.kind === "answer" ? response.synthesis.uncertainty : []), ...(response.kind === "insufficient_evidence" ? response.gaps : [])];
  const limitations = unique([
    LITE_SCOPE,
    `Corpus version: ${response.corpus_version}.`,
    response.kind === "insufficient_evidence" ? response.message : undefined,
    ...response.report_metadata.limitations,
    ...uncertainty,
  ]);

  return {
    mode: "lite",
    run: toRun(response),
    report: {
      run_id: response.run_id,
      verdict: response.kind === "answer" ? "Cited Lite answer" : "Insufficient evidence in Lite library",
      answer_markdown: response.kind === "answer" ? response.answer_markdown : null,
      workspace_scope: LITE_SCOPE,
      scores: {},
      atomic_claims: [{
        id: "lite-request",
        claim_text: response.request.input,
        importance_weight: 1,
        claim_type: response.classification?.input_type ?? response.request.input_type_hint ?? "question",
        final_label: response.kind === "answer" ? "Answered from curated evidence" : "Insufficient evidence",
        support_score: null,
        confidence_score: null,
        context_completeness: null,
        ambiguities: response.uncertainty,
        gaps: response.kind === "insufficient_evidence" ? response.gaps : [],
      }],
      evidence,
      source_graph: toSourceGraph(chunks, judgments),
      calculations: [],
      methodology_version: response.report_metadata.methodology_version,
      workflow_version: response.report_metadata.workflow_version,
      model_versions: response.report_metadata.model_versions,
      prompt_versions: response.report_metadata.prompt_versions,
      parser_versions: response.report_metadata.parser_versions,
      retrieval_versions: {
        ...response.report_metadata.retrieval_versions,
        corpus_version: response.corpus_version,
        retrieval_strategy: response.retrieval_strategy.name,
        retrieval_strategy_version: response.retrieval_strategy.version,
      },
      score_roles: response.report_metadata.score_roles,
      report_sentences: reportSentences,
      evidence_reviewed_at: response.report_metadata.evidence_reviewed_at,
      generated_at: response.reviewed_at,
      limitations,
    },
    sources,
    sourceGraph: toSourceGraph(chunks, judgments),
  };
}

export function isLiteReportResponse(response: LiteResponse | null): response is AdaptableLiteResponse {
  return response?.kind === "answer" || response?.kind === "insufficient_evidence";
}

function toRun(response: AdaptableLiteResponse): VerificationRun {
  return {
    run_id: response.run_id,
    status: "COMPLETED",
    input_type: response.classification?.input_type ?? response.request.input_type_hint ?? "question",
    research_depth: "Lite evidence library",
    title: response.kind === "answer" ? "Lite cited answer" : "Lite insufficient evidence report",
    verdict: response.kind === "answer" ? "Cited Lite answer" : "Insufficient evidence",
    queued_at: response.reviewed_at,
    started_at: response.reviewed_at,
    completed_at: response.reviewed_at,
    failed_at: null,
    cancellation_requested_at: null,
    failure_code: null,
    failure_message: null,
    updated_at: response.reviewed_at,
    saved_at: null,
    is_owner: false,
  };
}

function toSources(chunks: readonly LiteRetrievedChunk[], citations: LiteAnswerResponse["cited_sentences"]): SourceRecord[] {
  const grouped = new Map<string, LiteRetrievedChunk[]>();
  for (const chunk of chunks) {
    const key = chunk.document_id;
    grouped.set(key, [...(grouped.get(key) ?? []), chunk]);
  }

  return [...grouped.entries()].map(([documentId, documentChunks]) => {
    const first = documentChunks[0];
    const canonicalUrl = first.source_url ?? "";
    return {
      id: sourceId(documentId),
      canonical_url: canonicalUrl,
      domain: domainFromUrl(canonicalUrl) ?? "curated-lite-library",
      title: first.source_title,
      author: null,
      publisher: first.publisher ?? "Curated Lite library",
      source_type: "curated_lite_document",
      content_type: "stored evidence chunk",
      role: "curated_evidence",
      retrieval_reason: "Selected from the Lite stored evidence corpus for this request.",
      inaccessible_reason: null,
      snapshot_id: first.document_id,
      snapshot_version: null,
      access_status: "FETCHED",
      retrieved_at: first.reviewed_at,
      published_at: first.document_date ?? null,
      content_hash: first.content_hash,
      parser_name: "lite-corpus-ingestion",
      parser_version: String(first.metadata.parser_version ?? "lite-v1"),
      correction_status: null,
      correction_history: [],
      snapshot_metadata: {
        corpus_version: first.corpus_version,
        source_label: first.source_label,
        reviewed_at: first.reviewed_at,
        lite_scope: LITE_SCOPE,
        ...first.metadata,
      },
      failure_reason: null,
      passages: documentChunks.map((chunk) => toPassage(chunk, citations)),
    };
  });
}

function toPassage(chunk: LiteRetrievedChunk, citations: LiteAnswerResponse["cited_sentences"]): SourcePassage {
  const passageCitations: ReportCitation[] = citations
    .filter((sentence) => sentence.citation_ids.includes(chunk.chunk_id))
    .map((sentence) => ({
      id: `lite-citation-${sentence.sentence_index}-${chunk.chunk_id}`,
      report_section: "summary",
      sentence_text: sentence.text,
      passage_id: chunk.chunk_id,
      audit_status: sentence.support_status,
      audit_note: `Lite citation audit confidence ${Math.round(sentence.confidence * 100)}%.`,
    }));

  return {
    id: chunk.chunk_id,
    text: chunk.chunk_text,
    heading_path: chunk.heading_path ?? null,
    page_or_position: chunk.page_or_position ?? null,
    paragraph_index: chunk.paragraph_index ?? null,
    speaker: null,
    table_ref: null,
    extraction_certainty: chunk.retrieval_scores.combined,
    metadata: {
      source_label: chunk.source_label,
      content_hash: chunk.content_hash,
      retrieval_scores: chunk.retrieval_scores,
      retrieval_strategy: chunk.retrieval_strategy,
      reviewed_at: chunk.reviewed_at,
      ...chunk.metadata,
    },
    citations: passageCitations,
  };
}

function toEvidence(chunk: LiteRetrievedChunk, judgment: LiteEvidenceJudgment | undefined, index: number): ReportRecord["evidence"][number] {
  return {
    id: `lite-evidence-${chunk.chunk_id}`,
    atomic_claim_id: "lite-request",
    passage_id: chunk.chunk_id,
    stance: toStance(judgment),
    base_quality: Math.round(chunk.retrieval_scores.combined * 100),
    dependency_multiplier: 1,
    adjusted_weight: Math.round((judgment?.confidence ?? chunk.retrieval_scores.combined) * 100),
    citation_status: judgment?.stance ?? "selected_chunk",
    passage_text: judgment?.cited_span ?? chunk.chunk_text,
    source_title: chunk.source_title,
    source_url: chunk.source_url ?? sourceId(chunk.document_id),
    page_or_position: chunk.page_or_position ?? chunk.heading_path ?? `Lite chunk ${index + 1}`,
  };
}

function toStance(judgment: LiteEvidenceJudgment | undefined): EvidenceStance {
  if (!judgment) return "NEUTRAL";
  if (judgment.stance === "supports") return judgment.confidence >= 0.75 ? "STRONGLY_SUPPORTS" : "PARTIALLY_SUPPORTS";
  if (judgment.stance === "contradicts") return judgment.confidence >= 0.75 ? "STRONGLY_CONTRADICTS" : "PARTIALLY_CONTRADICTS";
  return "NEUTRAL";
}

function toSourceGraph(chunks: readonly LiteRetrievedChunk[], judgments: readonly LiteEvidenceJudgment[]): SourceGraphRecord {
  const nodes: SourceGraphRecord["nodes"] = [{
    id: "lite-request",
    type: "atomic_claim",
    label: "Lite request",
    data: { atomicClaimId: "lite-request" },
    position: { x: 0, y: 0 },
    metadata: { mode: "lite" },
  }];
  const edges: SourceGraphRecord["edges"] = [];

  chunks.forEach((chunk, index) => {
    const sourceNodeId = sourceId(chunk.document_id);
    const chunkNodeId = `lite-chunk:${chunk.chunk_id}`;
    const judgment = judgments.find((item) => item.chunk_id === chunk.chunk_id);
    if (!nodes.some((node) => node.id === sourceNodeId)) {
      nodes.push({
        id: sourceNodeId,
        type: "source",
        label: chunk.source_title,
        data: {
          sourceId: sourceNodeId,
          role: "curated_evidence",
          accessStatus: "FETCHED",
          atomicClaimIds: ["lite-request"],
          evidenceUsed: true,
          clusterId: "lite-library",
        },
        position: { x: 320, y: index * 120 },
        metadata: { source_label: chunk.source_label, corpus_version: chunk.corpus_version },
      });
      edges.push({
        id: `lite-request-${sourceNodeId}`,
        source: "lite-request",
        target: sourceNodeId,
        label: "retrieved",
        relationship: "RETRIEVED_FROM_CURATED_LIBRARY",
        confidence: chunk.retrieval_scores.combined,
        data: { detectionMethod: "Lite pgvector and lexical retrieval" },
      });
    }
    nodes.push({
      id: chunkNodeId,
      type: "snapshot",
      label: chunk.source_label,
      data: { sourceId: sourceNodeId, evidenceUsed: true, accessStatus: "FETCHED" },
      position: { x: 640, y: index * 120 },
      metadata: { chunk_id: chunk.chunk_id, stance: judgment?.stance ?? "selected" },
    });
    edges.push({
      id: `${sourceNodeId}-${chunkNodeId}`,
      source: sourceNodeId,
      target: chunkNodeId,
      label: judgment?.stance ?? "selected chunk",
      relationship: "CITES",
      confidence: judgment?.confidence ?? chunk.retrieval_scores.combined,
      data: { detectionMethod: "Lite citation-aware context selection" },
    });
  });

  return { nodes, edges };
}

function sourceId(documentId: string) {
  return `lite-source:${documentId}`;
}

function domainFromUrl(url: string) {
  if (!url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

function unique(values: Array<string | undefined>) {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}
