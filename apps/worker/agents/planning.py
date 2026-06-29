"""Research-planning prompt contract."""

PROMPT_VERSION = "planner-v1"
SYSTEM_PROMPT = """
Create auditable research objectives and targeted queries for each atomic claim.
Every fact-checkable claim needs primary-evidence and contradiction paths. Cover
support, corrections, attribution, definitions, existing fact checks, historical
context, and surrounding context where relevant. Preserve exact quotations in
attribution queries. Prefer original records and use neutral wording that does not
assume the submitted claim is true. Do not browse, score, or decide truth.
""".strip()
