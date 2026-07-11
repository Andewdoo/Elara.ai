import type { VerificationRun } from "@/hooks/use-run-events";

export type EvidenceStance =
  | "STRONGLY_CONTRADICTS"
  | "PARTIALLY_CONTRADICTS"
  | "NEUTRAL"
  | "PARTIALLY_SUPPORTS"
  | "STRONGLY_SUPPORTS";

export type CalculationRecord = {
  id: string;
  atomic_claim_id: string | null;
  formula_name: string;
  formula_text: string;
  inputs: Record<string, unknown>;
  result: Record<string, unknown>;
  units: string | null;
  decimal_context: Record<string, unknown>;
  audit_status: string;
};

export type ReportCitation = {
  id: string;
  report_section: string;
  sentence_text: string;
  passage_id: string;
  audit_status: string;
  audit_note: string | null;
};

export type SourcePassage = {
  id: string;
  text: string;
  heading_path: string | null;
  page_or_position: string | null;
  paragraph_index: number | null;
  speaker: string | null;
  table_ref: string | null;
  extraction_certainty: number;
  metadata: Record<string, unknown>;
  citations: ReportCitation[];
};

export type SourceRecord = {
  id: string;
  canonical_url: string;
  domain: string;
  title: string | null;
  author: string | null;
  publisher: string | null;
  source_type: string;
  content_type: string | null;
  role: string;
  retrieval_reason: string | null;
  inaccessible_reason: string | null;
  snapshot_id: string | null;
  snapshot_version: number | null;
  access_status: string;
  retrieved_at: string | null;
  published_at: string | null;
  content_hash: string | null;
  parser_name: string | null;
  parser_version: string | null;
  correction_status: string | null;
  correction_history: Array<{ snapshot_id: string; snapshot_version: number; status: string; retrieved_at: string }>;
  snapshot_metadata: Record<string, unknown>;
  failure_reason: string | null;
  passages: SourcePassage[];
};

export type SourceGraphRecord = {
  nodes: Array<{
    id: string;
    type: string;
    label: string;
    data: Record<string, unknown>;
    position: { x: number; y: number };
    metadata: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    label: string;
    relationship: string;
    confidence: number;
    data: Record<string, unknown>;
  }>;
};

export type ReportRecord = {
  run_id: string;
  verdict: string | null;
  answer_markdown?: string | null;
  workspace_scope?: string | null;
  scores: Record<string, number | null>;
  atomic_claims: Array<{
    id: string;
    claim_text: string;
    importance_weight: number;
    claim_type: string;
    final_label: string | null;
    support_score: number | null;
    confidence_score: number | null;
    context_completeness: number | null;
    ambiguities: string[];
    gaps: string[];
  }>;
  evidence: Array<{
    id: string;
    atomic_claim_id: string;
    passage_id: string;
    stance: EvidenceStance;
    base_quality: number;
    dependency_multiplier: number;
    adjusted_weight: number;
    citation_status: string;
    passage_text: string;
    source_title: string | null;
    source_url: string;
    page_or_position: string | null;
  }>;
  source_graph: SourceGraphRecord;
  calculations: CalculationRecord[];
  methodology_version: string;
  workflow_version: string;
  model_versions: Record<string, unknown>;
  prompt_versions: Record<string, unknown>;
  parser_versions: Record<string, unknown>;
  retrieval_versions: Record<string, unknown>;
  score_roles: Record<string, string>;
  report_sentences: ReportCitation[];
  evidence_reviewed_at: string;
  generated_at: string;
  limitations: string[];
};

export type ReportWorkspaceData = {
  mode?: "full" | "lite";
  run: VerificationRun;
  report: ReportRecord;
  sources: SourceRecord[];
  sourceGraph: SourceGraphRecord;
};
