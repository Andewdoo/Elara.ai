# Elara.ai

Elara.ai is an evidence-management and automated verification platform. It
evaluates a submitted claim, quotation, article, source document, or statement
against timestamped evidence and preserves the provenance needed to reproduce a
report. It is not a lie detector, a permanent credibility score, or a system
that calculates absolute truth.

## Public Lite Demo

The public demo is Elara Lite Mode. It is a stored-corpus cited RAG experience
that runs from the Next.js app on Vercel, retrieves curated evidence chunks from
Supabase Postgres with pgvector, and uses server-side DeepSeek synthesis plus
deterministic citation checks. Lite Mode is the first page at `/`; the complete
Full Mode verifier remains reachable at `/verify`.

Lite Mode demonstrates the Elara report workspace, citation language, source
presentation, and insufficient-evidence behavior over a bounded public evidence
library. It does not perform live open-web verification, user document
verification, private evidence storage, asynchronous worker processing, or the
complete production verifier workflow.

Lite v1 ships without a cached library of Full Mode responses. That cache is
deferred until Full Mode is completed, temporarily hosted, exercised with
controlled cases, and 10-20 high-quality completed reports are reviewed and
captured for public demo use.

See [project-context/operations/LITE_MODE.md](project-context/operations/LITE_MODE.md) for Vercel,
Supabase pgvector, seed corpus, DeepSeek, and public-demo deployment details.

## Full Mode Architecture

This repository also contains the full production verifier architecture:

- Next.js App Router frontend.
- FastAPI authentication, authorization, validation, durable read, export, SSE,
  and Celery enqueue boundary.
- PostgreSQL/pgvector durable data model managed through SQLAlchemy and Alembic.
- Redis Streams, Redis locks, and Celery queues for transient progress and
  asynchronous work.
- LangGraph-style worker stages for retrieval, extraction, evidence
  classification, scoring, numerical audit, synthesis, citation audit, and
  revision.
- Server-side DeepSeek, Brave Search, Firebase Authentication, private
  S3-compatible object storage, Sentry, and tracing integration.

Full Mode is paused after Step 25B staging evidence. It still requires paid
always-on infrastructure for the FastAPI API, Redis, Celery worker stack,
PostgreSQL, private object storage, and controlled live-provider validation
before it can be treated as production launch approved.

## Provider And Credential Boundary

Elara uses DeepSeek through server-side `DEEPSEEK_*` configuration only. Do not
add OpenAI APIs, OpenAI environment variables, browser-side model calls,
browser-side Supabase service-role access, or browser-side database writes.
Supabase is used only for Lite Mode's curated public-demo corpus and Lite demo
records; it does not replace the Full Mode PostgreSQL/FastAPI authorization
boundary.
