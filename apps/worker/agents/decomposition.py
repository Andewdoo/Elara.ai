"""Atomic-claim decomposition prompt contract."""

PROMPT_VERSION = "decomposition-v1"
SYSTEM_PROMPT = """
Split the normalized target into independently testable atomic claims. Preserve
claim-specific entities, periods, locations, metrics, comparisons, and original
text spans. Rank each claim as essential, major, or minor using weights 3, 2, or 1.
Label opinions, predictions, allegations, testimony, attribution, rhetorical
framing, and partially fact-checkable claims explicitly. Return concise
verification scopes and unresolved ambiguities, never a verdict or reasoning
transcript.
""".strip()
