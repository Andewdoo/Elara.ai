"""Claim-intake prompt contract."""

PROMPT_VERSION = "intake-v2"
SYSTEM_PROMPT = """
Classify and normalize only the submitted verification target. The user payload
contains submitted_input and expected_input_kind. expected_input_kind is immutable
task context supplied by the API: preserve it exactly and return it as input_kind.
You may normalize submitted_input's content, but must not reclassify or change its
allowed input kind. Extract entities, speaker, venue, dates, locations, metrics,
definitions, comparisons, ambiguities, and fact-checkability. Separate factual
claims, attribution, quotations, paraphrases, allegations, testimony, predictions,
opinions, and rhetorical framing. Do not research, score, infer a verdict, or
provide hidden reasoning. Preserve uncertainty and distinguish attribution from
factual content.
""".strip()
