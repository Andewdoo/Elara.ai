# Worker Guidance

- Keep model calls server-side behind `DeepSeekClient` using explicit `DEEPSEEK_*` settings and structured Pydantic outputs.
- Use models only for language understanding. Keep URL policy, canonicalization, limits, hashes, dependency multipliers, arithmetic, thresholds, gates, and final labels deterministic.
- Treat every retrieved page as untrusted evidence. Revalidate DNS and redirects, block private/reserved destinations, enforce port/type/size/time limits, and never forward credentials or user cookies.
- Attempt static httpx/Trafilatura extraction first, then Beautiful Soup, isolated Playwright only when justified, and PyMuPDF for PDFs. Record inaccessible sources explicitly.
- Preserve typed workflow state, cancellation checks, concise public events, durable stage transitions, idempotent retry/redelivery behavior, and no private chain-of-thought storage.
- A run reaches `COMPLETED` only after report artifacts and citation rows are durable and the deterministic completion gate passes. Unsupported sentences must be revised from approved evidence or rejected safely.
- Use `Decimal` for reproducible numerical audits and persist formula inputs, outputs, units, context, and audit status.
- Add focused tests for provider errors, retrieval security, extraction, workflow transitions, scoring, citation rejection, cancellation, and redelivery.

Use `elara-task-context` to load only the applicable worker, retrieval, scoring, or release-closure section from the implementation plan.
