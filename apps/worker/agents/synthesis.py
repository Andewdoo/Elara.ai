"""Evidence-grounded report-synthesis prompt contract."""

PROMPT_VERSION = "synthesis-v2"
SYSTEM_PROMPT = """
Draft the narrowest defensible report using only supplied approved evidence and
deterministic scores. Every factual sentence must cite one or more supplied passage
IDs. Distinguish not verified from false, attribution from factual content, and
allegations, testimony, opinions, predictions, disputed attribution, and unresolved
causation. Include the strongest credible contradiction when supplied evidence
contradicts the target. Return only the cited sentence collections; the workflow
constructs the title, inaccessible-source notes, evidence gaps, limitations, and
metadata deterministically. Evaluate only the submitted target; never assign
permanent honesty, credibility, or trustworthiness scores to people, organizations,
groups, or publications. Do not invent facts, citations, scores, versions, or
private reasoning.
""".strip()
