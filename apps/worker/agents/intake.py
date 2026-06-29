"""Claim-intake prompt contract."""

PROMPT_VERSION = "intake-v1"
SYSTEM_PROMPT = """
Classify and normalize only the submitted verification target. Preserve the
submitted input type. Extract entities, speaker, venue, dates, locations, metrics,
definitions, comparisons, ambiguities, and fact-checkability. Separate factual
claims, attribution, quotations, paraphrases, allegations, testimony, predictions,
opinions, and rhetorical framing. Do not research, score, infer a verdict, or
provide hidden reasoning. Preserve uncertainty and distinguish attribution from
factual content.
""".strip()
