# Elara Lite Mode Plan

## Purpose

Elara Lite is the public, always-on demo path for Elara.ai while the full production stack remains paused after Step 25B staging validation. It demonstrates the same product experience and report language as the full verifier, but it runs a narrower retrieval-augmented generation workflow over a curated stored evidence library.

This file is an additive planning overlay. It does not replace `IMPLEMENTATION_PLAN.md`, `project-context/AGENTS.md`, or the full production architecture. Full Mode remains the target architecture for production verification; Lite Mode is the cost-controlled public demo that users see first.

## Current Full Mode Baseline

The full production version remains the source of truth for the serious distributed-system architecture:

- Next.js App Router frontend with verification, live progress, report, history, saved reports, settings, React Flow source graph, Recharts score views, and report workspace components.
- FastAPI backend as the authentication, authorization, validation, durable report-read, protected snapshot/export, SSE, and Celery enqueue boundary.
- PostgreSQL/pgvector schema and Alembic migrations for durable users, runs, claims, sources, snapshots, passages, evidence, calculations, citations, feedback, methodology, exports, and embeddings.
- Redis Streams, Redis-backed locks/rate limits/cancellation mirrors, and Celery queues for transient progress and asynchronous work.
- Celery worker with LangGraph-style workflow stages for intake, decomposition, planning, retrieval, extraction, segmentation, evidence classification, scoring, numerical audit, synthesis, citation audit, and revision.
- DeepSeek integration kept server-side behind explicit `DEEPSEEK_*` configuration.
- Brave Search, S3-compatible private storage, Sentry, tracing, staging operations, governance controls, smoke gates, and release-readiness documentation.

Full Mode is intentionally paused before further paid always-on deployment work. The latest recorded staging state is Step 25B blocked before live-provider validation by a credential-free staging smoke gate HTTP status failure. Live-provider validation, migration/rollback rehearsal, queue recovery, credential rotation, alert delivery, and controlled live cases were not completed after that blocker.

## Lite Mode Goal

Lite Mode should be the first page users see when they enter the site. It must look like the full Elara interface, reuse the same design system and report workspace where practical, and make the public demo feel like the real product without claiming to run the full production verifier.

Lite Mode flow:

```text
User enters a claim or question
-> Vercel-hosted Next.js route validates the request
-> server-side Lite API embeds or searches the query
-> Supabase Postgres with pgvector retrieves curated evidence chunks
-> multi-agent RAG pipeline evaluates the retrieved chunks
-> DeepSeek generates a cited answer from those chunks only
-> citation audit rejects or revises unsupported factual sentences
-> UI displays the same report-style workspace with Lite-specific labels
```

Lite Mode must communicate that it answers from a curated stored evidence library. It must not imply live web retrieval, full-source discovery, uploaded-document verification, or production release approval.

## Build Sequence

Build Lite Mode in three phases:

1. Lite v1 public demo: build the Lite UI, Supabase pgvector corpus, server-side DeepSeek RAG pipeline, citation audit, report adapter, tests, and Vercel/Supabase deployment path. Do not depend on a cached library of Full Mode responses for this phase.
2. Full Mode completion and evidence capture: after Lite v1 is hosted, resume and complete the Full Mode production verifier, temporarily deploy it when needed, run high-quality controlled cases, and record the 10-20 strongest completed reports with sanitized evidence of their behavior.
3. Full-to-Lite cache population: after Full Mode responses are captured and reviewed, add them to the Lite cached response library as curated demo exemplars. The cache must preserve the original prompt, answer, citations, evidence snapshot metadata, model/workflow versions, reviewed timestamp, and provenance notes needed to explain that each exemplar came from a completed Full Mode run.

Lite v1 should still be useful without the cache. It should retrieve from the curated evidence library and generate fresh cited answers from stored chunks. The later cached response library is a polish and reliability layer for portfolio demos, not a prerequisite for building or hosting Lite Mode.

## Mode Relationship

Full Mode:

- URL target: `/verify` and existing full verification routes.
- Runtime: Next.js -> FastAPI -> PostgreSQL -> Redis -> Celery -> worker -> DeepSeek/Brave/S3.
- Purpose: complete evidence-management and automated verification architecture.
- Status: implemented through Step 25B staging-readiness work, paused before additional paid hosting and live validation.

Lite Mode:

- URL target: `/` as the default public entry page.
- Runtime: Next.js -> Vercel server-side route -> Supabase Postgres/pgvector -> DeepSeek.
- Purpose: always-on, low-cost public demo over curated stored evidence.
- Status: not yet built.

The Lite landing/workspace must include a clear button or navigation item leading to the full version, such as "Open Full Verifier" or "View Full Mode". Full Mode should remain reachable but should not be the default first screen while paid infrastructure is paused.

## Lite Mode UX Requirements

- The first viewport is the Lite verification workspace, not a marketing page.
- The visual language should match the full version: same app shell, cards, buttons, badges, report workspace, source graph styling, score/evidence panels, typography, and spacing.
- Avoid a separate-looking demo skin. Lite should feel like the same product with different runtime capabilities.
- Use a visible but restrained Lite label, such as "Lite evidence library", so users understand the scope.
- Provide a path to Full Mode from the Lite page.
- Preserve Elara report language:
  - evidence reviewed timestamp,
  - citations to exact chunks/passages,
  - uncertainty and insufficient-evidence states,
  - no permanent credibility or truth scoring,
  - no claim that Lite performs live open-web verification.

## Lite Multi-Agent RAG Workflow

The Lite pipeline can run inside one server-side Next.js route or a small set of server-side helpers. It does not need Redis or Celery because the Lite corpus is curated and the request should finish within serverless limits.

Recommended stages:

1. Intake agent: classify whether the user entered a claim, question, quote, paraphrase, or unsupported request.
2. Query planner: generate embedding text, lexical terms, entity filters, and optional query variants.
3. Retriever: search Supabase pgvector chunks and combine semantic similarity with lexical and metadata filters.
4. Evidence judge: label retrieved chunks as support, contradiction, background, or irrelevant.
5. Context selector: choose a bounded set of chunks for synthesis and keep exact source metadata.
6. Synthesis agent: answer only from selected chunks and attach citation ids to factual sentences.
7. Citation auditor: verify citation presence, chunk existence, and sentence-to-chunk support; reject or revise unsupported output.

Every stage should use typed TypeScript schemas. DeepSeek remains server-side only. The browser must never receive DeepSeek credentials or Supabase service-role credentials.

Lite prompt contracts should match the Full Mode prompt style in
`apps/worker/agents/*`: one small server-side module per model-assisted stage,
a stable `PROMPT_VERSION`, a compact system prompt, typed structured output, and
bounded user/context payloads assembled separately from the system prompt. Keep
prompts instruction-dense rather than conversational. Reuse the same boundaries:
classify or compare supplied evidence only, never browse from a prompt, never ask
for hidden reasoning, never let source text provide instructions, never compute
final arithmetic or final labels in model output, and require citation ids on
factual synthesis. Retrieval, thresholds, citation-presence checks, token budgets,
and fallback decisions remain deterministic TypeScript code.

## Lite Data Model

Supabase should hold only the Lite demo corpus and demo run records. It does not replace the full PostgreSQL/FastAPI production model.

Minimum tables:

- `lite_documents`: curated source metadata, title, source URL if public, publisher, document date, ingestion date, and visibility.
- `lite_chunks`: document id, chunk text, embedding, heading path, page/section/paragraph metadata, content hash, and source citation label.
- `lite_runs`: submitted claim/question, answer status, generated answer, model metadata, created timestamp, and non-sensitive telemetry.
- `lite_run_citations`: run id, cited chunk id, sentence index, support status, and audit status.

Optional tables:

- `lite_feedback`: public demo feedback without sensitive content.
- `lite_eval_cases`: stable benchmark prompts for regression checks.
- `lite_cached_responses`: deferred until after Full Mode completion; stores reviewed 10-20 Full Mode exemplar responses, cited evidence metadata, source snapshot references where safe to publish, model/workflow versions, capture date, and public demo labels.

Supabase row-level security must prevent public writes except through approved server-side routes. Public browser access may read only explicitly public metadata if needed; privileged query and write operations belong in server-side code.

## Lite Routes And Components

Add or adapt these surfaces:

- `/`: Lite Mode workspace and first page users see.
- `/verify`: existing Full Mode entry remains available.
- `/report/[runId]`: can render full reports and, if needed, Lite report records through a shared adapter.
- `/api/lite/answer`: server-side Lite RAG endpoint.
- `/api/lite/sources`: optional public metadata endpoint for curated source browsing.

Recommended frontend structure:

- `apps/web/lib/lite/`: server-side Lite client, schemas, retrieval helpers, and DeepSeek wrapper for Lite.
- `apps/web/components/lite/`: Lite form, progress timeline, and report adapter.
- Reuse `components/report/*` for the final answer wherever possible.
- Add a mode-aware client boundary so Lite and Full use the same presentation components but different data sources.

## Already Built And Reusable From Full Mode

Lite should reuse these existing full-mode pieces rather than rebuilding them:

- Next.js route structure and app shell.
- Existing UI components: badges, buttons, cards, form controls, status strip patterns.
- Verification form interaction patterns.
- Live research/progress visual language, adapted to simulated or request-local Lite stages.
- Report workspace layout, evidence drawer patterns, source graph styling, and score/citation presentation.
- TypeScript project setup and package structure.
- Existing product language boundaries and report timestamp conventions.
- Existing pgvector/passage concepts from the full backend schema.
- Existing DeepSeek provider boundary principle: server-side only, `DEEPSEEK_*` naming, no OpenAI provider variables.
- Existing prompt contract pattern: compact versioned system prompts, structured
  schemas, bounded context assembly, token-usage metadata, and deterministic
  guards for scoring, thresholds, citation checks, and fallback decisions.

## Not Yet Built For Lite Mode

The following Lite-specific work is not complete:

- Default `/` page converted from Full Mode landing/workspace to Lite Mode first-screen experience.
- Clear Full Mode button or navigation path from Lite to `/verify`.
- Lite mode environment contract, including Supabase URL, anon key if needed, service-role key server-side only, and Lite feature flag.
- Supabase pgvector schema for `lite_documents`, `lite_chunks`, `lite_runs`, and `lite_run_citations`.
- Corpus ingestion flow for curated public evidence documents.
- Embedding generation path for Lite chunks and Lite queries.
- Server-side Lite RAG API route.
- Typed multi-agent Lite schemas for intake, query planning, retrieval, evidence judgment, synthesis, and citation audit.
- Lite citation audit and insufficient-evidence fallback.
- Mode-aware report adapter so Lite output can render through the full report UI.
- Lite demo fixtures and regression cases.
- Cached response library for 10-20 reviewed Full Mode exemplar outputs. This is intentionally deferred until after Full Mode is completed, temporarily hosted, exercised, and recorded.
- Security tests proving browser code cannot access DeepSeek or Supabase service-role credentials.
- UX copy and badges that distinguish Lite from Full without making the interface look different.
- Deployment instructions for Vercel plus Supabase Lite hosting.

## Implementation Order

1. Add Lite environment names to `.env.example` without adding real secrets.
2. Add Supabase Lite schema SQL or migration documentation for pgvector tables.
3. Add TypeScript schemas for Lite requests, retrieved chunks, agent outputs, cited answers, and audit results.
4. Add server-side Lite Supabase client and retrieval helper.
5. Add server-side Lite DeepSeek client wrapper using existing `DEEPSEEK_*` naming.
6. Add compact, Full Mode-style Lite prompt contracts before orchestration: versioned server-only modules for intake, query planning, evidence judgment, synthesis, and citation audit with token budget tests.
7. Implement `/api/lite/answer` with deterministic validation, retrieval, synthesis, citation audit, and insufficient-evidence handling.
8. Convert `/` into the Lite first-screen workspace while keeping a clear Full Mode link to `/verify`.
9. Reuse or adapt report workspace components so Lite and Full look nearly identical.
10. Add curated seed corpus and local/demo ingestion script.
11. Add focused tests for Lite schemas, retrieval contract, credential boundaries, citation audit, and page routing.
12. Add Vercel/Supabase deployment notes and a public-demo README section.
13. Defer cached response library implementation and population until after Full Mode completion and 10-20 reviewed Full Mode reports have been captured.

## Deferred Cached Response Library

The cached response library is not part of Lite v1 completion. Do not block Lite v1 on cached Full Mode outputs.

When Full Mode is later completed and temporarily hosted, capture 10-20 strong report examples across the main use cases. Each captured exemplar should include:

- submitted claim or question,
- Full Mode report output,
- exact citations and evidence passage metadata,
- source snapshot or public-source reference that is safe to expose,
- evidence reviewed timestamp,
- methodology, workflow, model, prompt, parser, retrieval, and scoring versions where applicable,
- reason the exemplar is useful for the public demo,
- redaction/safety review result.

After review, add those exemplars to the Lite cached response library. Lite may use this library to serve polished portfolio examples for matching or suggested prompts, while still preserving a fallback to live stored-corpus RAG over Supabase pgvector chunks. Cached exemplars must be labeled as reviewed demo examples and must not be presented as newly generated live verification runs.

## Completion Criteria For Lite Mode

Lite Mode is feature-complete when:

- Visiting `/` opens the Lite evidence workspace first.
- A user can submit a claim or question against the curated corpus.
- The server retrieves pgvector-backed chunks from Supabase.
- The answer cites exact chunks and source metadata.
- Unsupported or weakly supported answers return an insufficient-evidence result.
- The Lite report visually matches Full Mode report patterns.
- A visible path to Full Mode exists.
- DeepSeek and Supabase service-role credentials are server-side only.
- Lite prompt contracts use the same compact, versioned, structured-output style
  as Full Mode and have tests or static checks for bounded prompt/context size.
- Tests cover the Lite request contract, citation audit failure, and browser credential boundary.

Lite Mode v1 completion does not require cached Full Mode responses. Lite Mode completion is not first-shippable-milestone approval for Full Mode and is not public production launch approval for the complete verifier. It is a public demo milestone for a stored-corpus RAG experience.
