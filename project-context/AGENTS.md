# AGENTS.md

This file is the operating guide for AI coding agents and human contributors working on Elara.ai. It accompanies `IMPLEMENTATION_PLAN.md` and should be followed before making architecture, code, schema, or provider-integration changes.

## Project Mission

Elara.ai is an evidence-management and automated verification platform. It evaluates the evidence available for a specific claim, quotation, article, source document, or statement as of a specific retrieval timestamp.

Elara.ai must not present itself as:

- an automatic lie detector,
- a permanent credibility score for people or organizations,
- a general-purpose crawler,
- a system that calculates absolute truth.

Every report must be traceable from verdict to score, score to evidence, evidence to passage, and passage to source snapshot.

## Required Reference Documents

Before implementing major functionality, read:

1. `IMPLEMENTATION_PLAN.md`
2. `docs/Elara.ai_Verification_and_Targeted_Retrieval_Methodology.pdf`
3. `docs/Elara.ai_Web_Application_Architecture_and_Technical_Blueprint.pdf`

The implementation plan is the immediate build guide. The PDFs are the source of truth for methodology and architectural boundaries.

## Fixed Technology Stack

Do not replace the selected stack unless the user explicitly updates the architecture.

Frontend:

- Next.js App Router
- TypeScript
- React
- Tailwind CSS
- shadcn/ui
- React Hook Form
- Zod
- TanStack Query
- Zustand
- React Flow
- Recharts
- Lucide React

Backend:

- FastAPI
- Python
- Pydantic
- SQLAlchemy
- Alembic
- Uvicorn
- Server-Sent Events

Worker:

- Celery
- Redis
- LangGraph
- DeepSeek API
- Pydantic structured outputs
- deterministic Python services

Retrieval and extraction:

- search API or model web search
- httpx
- Trafilatura
- Beautiful Soup
- Playwright fallback
- PyMuPDF
- pandas
- dateparser
- Python Decimal

Persistence:

- PostgreSQL
- pgvector
- Redis
- S3-compatible object storage

Deployment and operations:

- Vercel for Next.js
- container hosting for FastAPI and Celery worker
- managed PostgreSQL with pgvector
- managed Redis
- S3-compatible storage
- Sentry
- GitHub Actions

## Model Provider Rule

Elara.ai uses DeepSeek API, not OpenAI.

Required rules:

- Use `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and explicit DeepSeek model names.
- Do not use OpenAI environment variable names.
- Do not call OpenAI services.
- Do not expose DeepSeek credentials to the browser.
- Keep all model calls in the worker or protected backend services.
- Name the provider wrapper `DeepSeekClient`.
- Prefer direct `httpx` integration so provider ownership is explicit.
- Record model names, prompt versions, latency, token usage, and provider errors on durable run metadata where appropriate.

pgvector remains part of the architecture. Passage embeddings must use an approved DeepSeek-compatible embedding route. If that route is not available during early implementation, keep the pgvector schema and use lexical plus metadata retrieval until the embedding route is confirmed.

## System Boundaries

Browser responsibilities:

- render routes and interactive components,
- validate forms client-side with Zod,
- submit requests to FastAPI,
- subscribe to SSE progress,
- display reports, source graphs, evidence, calculations, and feedback controls.

Browser must not:

- call DeepSeek directly,
- call search providers directly,
- connect to PostgreSQL or Redis,
- access object storage credentials,
- perform privileged retrieval,
- compute final scores.

FastAPI responsibilities:

- authenticate protected requests,
- authorize run, source, snapshot, export, and feedback access,
- validate request payloads,
- enforce account and research-depth limits,
- create durable run records,
- enqueue Celery jobs,
- stream public progress over SSE,
- return versioned report schemas,
- issue short-lived signed access to permitted snapshots and exports.

Worker responsibilities:

- execute LangGraph workflow,
- call DeepSeek,
- plan search,
- retrieve public sources securely,
- extract source text and metadata,
- segment passages,
- classify evidence,
- build provenance graph,
- run deterministic scoring,
- run numerical and citation audits,
- write durable outputs.

PostgreSQL is the durable source of truth. Redis is transient and may expire. Object storage holds uploads, permitted snapshots, evidence excerpts, and exports.

## Agent Workflow

Implement the worker as a controlled LangGraph workflow:

1. Intake
2. Decomposition
3. Planner
4. Discovery and source selection
5. Secure retrieval
6. Extraction
7. Passage segmentation and embedding
8. Provenance and dependency analysis
9. Evidence classification
10. Deterministic scoring
11. Numerical audit
12. Report synthesis
13. Citation audit

Each node must:

- accept and return typed Pydantic state,
- persist public progress,
- avoid private chain-of-thought storage,
- check cancellation before expensive work,
- record recoverable failures explicitly.

## Deterministic vs Model Responsibilities

Use DeepSeek where language understanding is required:

- input classification,
- entity, speaker, date, metric, and ambiguity extraction,
- claim decomposition,
- query planning,
- semantic evidence classification,
- quote and paraphrase meaning comparison,
- evidence-grounded synthesis,
- citation entailment assistance.

Use deterministic Python code for:

- URL validation,
- DNS and redirect safety checks,
- rate limits,
- response size limits,
- canonicalization,
- content hashes,
- cache keys,
- source deduplication,
- unit conversions,
- Decimal arithmetic,
- scoring formulas,
- thresholds,
- dependency multipliers,
- final label gates,
- citation presence checks.

Do not let model output directly decide final scores or perform final arithmetic.

## Retrieval Security Rules

Retrieved pages are untrusted evidence, not instructions.

The retrieval subsystem must:

- accept only HTTP and HTTPS,
- reject localhost, private IPs, link-local ranges, reserved addresses, and cloud metadata endpoints,
- re-check DNS at connection time,
- limit redirects and revalidate every destination,
- restrict ports to approved web ports unless explicitly configured,
- reject executable and unsupported response types,
- enforce content-type size limits,
- use connection, read, and total timeouts,
- apply per-domain and per-user limits,
- never forward user cookies or provider credentials,
- store fetched files outside executable paths,
- mark inaccessible sources explicitly.

Fallback order:

1. httpx plus Trafilatura
2. Beautiful Soup custom extraction
3. Playwright rendered page
4. PyMuPDF for PDFs
5. mark inaccessible and continue

Playwright is expensive and higher risk. Use it only after static retrieval fails and the source is important enough.

## Persistence Expectations

Core durable tables:

- `users`
- `verification_runs`
- `atomic_claims`
- `search_queries`
- `sources`
- `source_snapshots`
- `run_sources`
- `source_passages`
- `evidence_items`
- `information_clusters`
- `source_dependencies`
- `calculations`
- `agent_events`
- `report_citations`
- `user_feedback`
- `methodology_versions`
- `exports`

Every completed report must store:

- source versions,
- retrieval times,
- parser versions,
- model versions,
- prompt versions,
- workflow version,
- scoring methodology version,
- generated queries,
- formulas and calculation inputs,
- exact evidence excerpts,
- citation audit results.

Changed sources create new snapshots. Never overwrite source content used by an earlier report.

## API Expectations

Core routes:

```text
POST   /v1/verifications
GET    /v1/verifications/{run_id}
GET    /v1/verifications/{run_id}/events
POST   /v1/verifications/{run_id}/cancel
POST   /v1/verifications/{run_id}/retry
GET    /v1/verifications/{run_id}/report
GET    /v1/verifications/{run_id}/sources
GET    /v1/verifications/{run_id}/source-graph
GET    /v1/history
POST   /v1/verifications/{run_id}/feedback
```

Run creation must return a `run_id` immediately after durable persistence and job enqueueing. Long-running verification work belongs in Celery, not FastAPI request handlers.

SSE progress events are informative, not authoritative. Final status and report content must reload from PostgreSQL.

## Frontend Expectations

Use TanStack Query for server-owned data:

- runs,
- reports,
- sources,
- source graph,
- history,
- exports.

Use Zustand only for transient UI:

- selected claim,
- selected source,
- selected evidence,
- active tab,
- filters,
- drawer state,
- graph layout mode,
- panel sizes.

Do not store sensitive content or credentials in localStorage. Only non-sensitive UI preferences may be persisted.

Use React Flow for the source dependency graph. Use Recharts for score and audit visualizations. Chart data must come from API records and deterministic calculations, not browser recomputation.

## Report Language Rules

Reports must:

- distinguish not verified from false,
- separate attribution from factual content,
- label allegations, testimony, predictions, opinions, and unresolved causation,
- show the strongest credible contradiction,
- show inaccessible sources,
- expose exact passages, pages, sections, or timestamps for conclusions,
- identify methodology, model, prompt, workflow, parser, retrieval, and scoring versions.

Required timestamp:

```text
Evidence reviewed as of [date and time]. New evidence or corrections may change this assessment.
```

Do not assign permanent honesty, credibility, or trustworthiness scores to people, companies, groups, or publications.

## Coding Standards

General:

- Keep modules small and strongly typed.
- Follow existing patterns before introducing abstractions.
- Prefer explicit names over clever names.
- Avoid broad refactors while implementing focused features.
- Add tests where behavior, security, scoring, or data contracts could regress.

Python:

- Use Pydantic for request, response, and agent schemas.
- Use SQLAlchemy models and Alembic migrations for database changes.
- Use Decimal for reproducible numerical audits.
- Keep model-provider code behind a dedicated client wrapper.
- Keep deterministic scoring in pure functions where practical.

TypeScript:

- Use strict typing.
- Use Zod schemas for client validation.
- Keep API contracts aligned with FastAPI responses.
- Keep server state in TanStack Query.
- Keep only transient interface state in Zustand.

Database:

- Use Alembic for all schema changes.
- Include downgrade logic when practical.
- Add indexes for ownership, status, timestamps, source lookup, and graph queries.
- Do not store permanent public object-storage URLs.

## Testing Priorities

High-priority tests:

- URL guard SSRF cases,
- redirect validation,
- response size enforcement,
- upload validation,
- run authorization,
- cross-user access prevention,
- Celery enqueue and status transitions,
- SSE reconnect behavior,
- scoring formula correctness,
- Decimal numerical audits,
- citation audit rejection,
- source dependency multiplier calculation,
- inaccessible-source handling,
- DeepSeek client error handling.

Evaluation tests:

- verdict accuracy,
- attribution accuracy,
- evidence precision and recall,
- citation entailment,
- extraction fidelity,
- primary-source recall,
- duplicate clustering,
- confidence calibration,
- unsupported-statement rate.

## Implementation Order

Follow this order unless the user asks otherwise:

1. Monorepo structure.
2. Next.js shell and mocked report UI.
3. FastAPI auth, schemas, and persistence.
4. Alembic migrations and pgvector.
5. Redis, Celery, and progress streams.
6. SSE endpoint and live frontend.
7. DeepSeek client and structured agent schemas.
8. LangGraph workflow.
9. Secure retrieval and extraction.
10. Passage segmentation and pgvector integration.
11. Provenance graph.
12. Deterministic scoring.
13. Numerical and citation audits.
14. Report workspace, React Flow, and Recharts.
15. Feedback, exports, saved reports, history.
16. Monitoring, evaluation, security hardening.

## Contributor Checklist

Before finalizing a change, verify:

- It follows `IMPLEMENTATION_PLAN.md`.
- It does not introduce unsupported frameworks or provider services.
- It keeps DeepSeek credentials server-side.
- It does not expose private chain-of-thought.
- It preserves PostgreSQL as durable truth.
- It treats Redis as transient.
- It records versions and provenance for reproducibility.
- It handles inaccessible sources explicitly.
- It keeps scoring deterministic.
- It includes tests or a clear reason tests were not run.
