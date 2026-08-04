import { create } from "zustand";

export type ReportTab = "overview" | "claims" | "evidence" | "graph";
export type EvidenceFilter = "all" | "supporting" | "contradicting" | "neutral" | "inaccessible";
export type GraphLayoutMode = "dependency" | "cluster";

type ReportUiState = {
  selectedClaimId: string | null;
  selectedSourceId: string | null;
  selectedEvidenceId: string | null;
  activeReportTab: ReportTab;
  evidenceFilter: EvidenceFilter;
  sourceDrawerOpen: boolean;
  graphLayoutMode: GraphLayoutMode;
  workspacePanelSizes: [number, number, number];
  selectClaim: (claimId: string | null) => void;
  selectSource: (sourceId: string | null) => void;
  selectEvidence: (evidenceId: string | null) => void;
  setActiveReportTab: (tab: ReportTab) => void;
  setEvidenceFilter: (filter: EvidenceFilter) => void;
  setSourceDrawerOpen: (open: boolean) => void;
  setGraphLayoutMode: (mode: GraphLayoutMode) => void;
};

export const useReportUiStore = create<ReportUiState>((set) => ({
  selectedClaimId: null,
  selectedSourceId: null,
  selectedEvidenceId: null,
  activeReportTab: "overview",
  evidenceFilter: "all",
  sourceDrawerOpen: true,
  graphLayoutMode: "dependency",
  workspacePanelSizes: [22, 52, 26],
  selectClaim: (selectedClaimId) => set({ selectedClaimId }),
  selectSource: (selectedSourceId) => set({ selectedSourceId, sourceDrawerOpen: true }),
  selectEvidence: (selectedEvidenceId) => set({ selectedEvidenceId }),
  setActiveReportTab: (activeReportTab) => set({ activeReportTab }),
  setEvidenceFilter: (evidenceFilter) => set({ evidenceFilter }),
  setSourceDrawerOpen: (sourceDrawerOpen) => set({ sourceDrawerOpen }),
  setGraphLayoutMode: (graphLayoutMode) => set({ graphLayoutMode }),
}));
