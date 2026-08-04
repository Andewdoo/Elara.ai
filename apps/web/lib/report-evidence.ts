export type EvidenceCategory = "supporting" | "contradicting" | "neutral";

const evidenceStanceCategories: Record<string, EvidenceCategory> = {
  STRONGLY_SUPPORTS: "supporting",
  PARTIALLY_SUPPORTS: "supporting",
  STRONGLY_CONTRADICTS: "contradicting",
  PARTIALLY_CONTRADICTS: "contradicting",
  NEUTRAL: "neutral",
};

export function evidenceCategoryForStance(stance: unknown): EvidenceCategory | null {
  return typeof stance === "string" ? evidenceStanceCategories[stance] ?? null : null;
}

export function groupEvidenceByStance<T extends { stance: unknown }>(items: T[]) {
  const groups: Record<EvidenceCategory, T[]> = {
    supporting: [],
    contradicting: [],
    neutral: [],
  };
  const invalid: T[] = [];

  for (const item of items) {
    const category = evidenceCategoryForStance(item.stance);
    if (category) groups[category].push(item);
    else invalid.push(item);
  }

  return { groups, invalid };
}
