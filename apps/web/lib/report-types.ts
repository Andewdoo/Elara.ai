export type RunStatus =
  | "QUEUED"
  | "VALIDATING"
  | "DECOMPOSING"
  | "RESEARCHING"
  | "EXTRACTING"
  | "ANALYZING_PROVENANCE"
  | "SCORING"
  | "SYNTHESIZING"
  | "AUDITING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type ResearchDepth = "QUICK" | "STANDARD" | "DEEP";
export type EvidenceStance =
  | "STRONGLY_CONTRADICTS"
  | "PARTIALLY_CONTRADICTS"
  | "NEUTRAL"
  | "PARTIALLY_SUPPORTS"
  | "STRONGLY_SUPPORTS";
export type AccessStatus = "FETCHED" | "INACCESSIBLE" | "PAYWALLED" | "BOT_BLOCKED" | "UNSUPPORTED" | "FAILED";

export type ScoreRecord = {
  key: string;
  label: string;
  value: number;
  maxValue: number;
  source: "calculation_record";
  calculationId: string;
};

export type EvidenceBalanceRecord = {
  atomicClaimId: string;
  claimLabel: string;
  supportingAdjustedWeight: number;
  contradictingAdjustedWeight: number;
  source: "calculation_record";
  calculationId: string;
};

export type SourceRecord = {
  id: string;
  title: string;
  publisher: string;
  domain: string;
  sourceType: string;
  accessStatus: AccessStatus;
  retrievedAt: string | null;
  parserName: string | null;
  parserVersion: string | null;
  snapshotId: string | null;
  retrievalReason: string;
  inaccessibleReason?: string;
};

export type EvidenceItemRecord = {
  id: string;
  atomicClaimId: string;
  sourceId: string;
  passageId: string;
  stance: EvidenceStance;
  stanceValue: number;
  adjustedWeight: number;
  quality: {
    relevance: number;
    directness: number;
    authority: number;
    transparency: number;
    temporalFit: number;
    extractionCertainty: number;
    dependencyMultiplier: number;
  };
  excerpt: string;
  passageLocator: string;
  citationStatus: "accepted" | "pending" | "rejected";
};

export type AtomicClaimRecord = {
  id: string;
  claimText: string;
  claimType: string;
  importanceWeight: 1 | 2 | 3;
  finalLabel: string;
  supportScore: number;
  confidenceScore: number;
  contextCompleteness: number;
  gaps: string[];
};

export type CalculationRecord = {
  id: string;
  formulaName: string;
  formulaText: string;
  inputs: Record<string, string | number>;
  result: Record<string, string | number>;
  units: string | null;
  decimalContext: {
    precision: number;
    rounding: string;
  };
  auditStatus: "passed" | "needs_review";
};

export type MethodologyRecord = {
  methodologyVersion: string;
  workflowVersion: string;
  scoringVersion: string;
  promptVersions: Record<string, string>;
  modelVersions: Record<string, string>;
  parserVersions: Record<string, string>;
  retrievalConfigVersion: string;
};

export type SourceGraphRecord = {
  nodes: Array<{
    id: string;
    type: "source" | "snapshot" | "cluster";
    label: string;
    data: {
      sourceId?: string;
      accessStatus?: AccessStatus;
      role?: string;
    };
    position: { x: number; y: number };
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    label: string;
    data: {
      relationship: string;
      confidence: number;
      detectionMethod: string;
    };
  }>;
};

export type ReportRecord = {
  runId: string;
  status: RunStatus;
  title: string;
  inputType: "CLAIM" | "ARTICLE_URL" | "ARTICLE_TEXT" | "QUOTE" | "PARAPHRASE" | "UPLOADED_DOCUMENT";
  researchDepth: ResearchDepth;
  submittedAt: string;
  evidenceReviewedAt: string;
  evidenceTimestampText: string;
  verdict: string;
  verdictSummary: string;
  limitations: string[];
  scoreRecords: ScoreRecord[];
  evidenceBalanceRecords: EvidenceBalanceRecord[];
  confidenceComponentRecords: ScoreRecord[];
  coverageRecords: ScoreRecord[];
  atomicClaims: AtomicClaimRecord[];
  sources: SourceRecord[];
  evidenceItems: EvidenceItemRecord[];
  inaccessibleSources: SourceRecord[];
  calculations: CalculationRecord[];
  methodology: MethodologyRecord;
  sourceGraph: SourceGraphRecord;
};
