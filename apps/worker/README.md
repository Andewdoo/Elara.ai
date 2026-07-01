# Elara Worker

Celery and LangGraph worker for evidence retrieval, extraction, provenance, deterministic scoring, numerical audits, report synthesis, and citation audits.

Model calls belong behind the server-side `DeepSeekClient` wrapper. Retrieved content is untrusted evidence and must never alter workflow policy, credentials, scoring formulas, or final verdict logic.

The Step 5 worker registers `verification.verify_run`, uses a per-run Redis lock,
loads the authoritative run from PostgreSQL, checks both durable and transient
cancellation flags, and mirrors public events to PostgreSQL plus the Redis Stream
`elara:run:{run_id}:events`. It performs bounded retries only for explicitly mapped
transient provider and fetch errors.

Step 7 adds the server-side `agents.deepseek_client.DeepSeekClient`, using
`httpx.AsyncClient` for low-temperature JSON calls. It returns validated Pydantic
outputs together with model, prompt-version, latency, response-id, and token-usage
metadata. Provider failures expose redacted operational metadata and retryable
failures inherit the worker's existing transient-provider contract. Raw prompts,
source passages, credentials, and provider response bodies are never logged.
The client also prepends a fixed boundary that treats submitted and retrieved
content as untrusted evidence rather than executable instructions.

Structured language-agent contracts live in `agents.schemas` for intake,
decomposition, planning, evidence classification, report synthesis, and citation
auditing. These schemas do not calculate scores or authorize a run to complete;
those decisions remain deterministic workflow controls.

Step 8 adds the controlled workflow in `graph`. `VerificationState` is a strict
Pydantic contract for every durable/auditable artifact and contains no prompt or
private-reasoning fields. Intake, decomposition, planning, evidence classification,
synthesis, and citation audit use DeepSeek only for language understanding. Python
guards validate all claim, objective, passage, and citation references and recompute
citation-audit completion flags. Every node checks cancellation, writes public
progress, and records a typed recoverable error before stopping safely.

The workflow validates the declared input type, enforces primary and contradiction
paths per fact-checkable claim, treats extraction certainty and citation presence as
deterministic controls, and emits public progress across all 13 methodology stages.
Provider failures retain only redacted operational details in durable public events.
Non-retryable graph stops become concise durable run failures, while retryable
provider failures retain the bounded Celery retry policy. Citation audit rows and
the final completion gate are deterministic; a report needing citation revision is
never eligible for `COMPLETED`.

Typed extension hooks reserve the full methodology sequence for discovery/source
selection, secure retrieval, extraction, passage segmentation/embedding,
provenance/dependency analysis, deterministic scoring, and numerical audit. A
`planning_only` compilation mode provides the safe Step 8 production handoff until
those later implementations are installed.

Step 9 installs the first three hooks. `research` contains the server-only Brave
Search client, deterministic usefulness ranking, Redis search/fetch cache and rate
limits, URL guard, and bounded `httpx` fetcher. The fetcher accepts only HTTP(S),
pins validated public DNS addresses at connection time, revalidates redirects,
never forwards user credentials, rejects unsupported/executable or oversized
responses, stages bytes outside worker code paths, and writes private content-addressed
objects to S3-compatible storage when credentials are configured. `extraction` applies
Trafilatura, Beautiful Soup, the explicit future Playwright boundary, and page-aware
PyMuPDF parsing. PostgreSQL stores every selected source, immutable snapshot, run
link, parser version, and explicit inaccessible status before the workflow hands off
to Step 10 passage segmentation.

Step 10 adds structure-aware passage segmentation, stable text hashing, the
approved server-side DeepSeek embedding route, pgvector persistence, and a
lexical/metadata fallback when embeddings are unavailable.

Step 11 installs deterministic provenance analysis. It detects outbound and
named citations, first-known copies, syndication, near-duplicate text, shared
quotations, statistics, tables, and correction/error fragments. Information
clusters and dependency edges are persisted before scoring, with contribution
multipliers fixed at 1.00, 0.35, 0.10, or 0.00. The protected FastAPI source
graph endpoint exports run-scoped source, snapshot, and cluster nodes plus
auditable relationship metadata for React Flow.

Step 12 installs pure-Python Decimal scoring in `scoring`. The published quality,
dependency, evidence balance, support, consistency, confidence, independence,
quote-fidelity, context, and article formulas are isolated from model output.
Deterministic insufficient-evidence, misleading-context, confidence, and essential-
claim gates produce final labels. Accepted and rejected evidence weights, per-claim
scores, overall scores, formula text, inputs, results, units, Decimal context, and
audit status are persisted before the workflow hands off to numerical auditing.
