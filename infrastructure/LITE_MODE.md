# Lite Mode infrastructure note

Lite Mode is an additive public demo path for Elara.ai. It runs from the
Vercel-hosted Next.js app and queries a curated Supabase Postgres/pgvector corpus
through server-side routes and helpers. It is not the complete production verifier.

Full Mode remains the production architecture for verification work: Next.js calls
FastAPI, FastAPI enforces authentication and authorization, PostgreSQL/pgvector is
durable truth, Redis and Celery coordinate asynchronous work, the worker runs the
LangGraph-style workflow, Brave Search and private S3-compatible storage stay
server-side, and DeepSeek is called only through `DEEPSEEK_*` server configuration.

Lite Mode environment ownership:

- Browser-readable Lite values must use `NEXT_PUBLIC_*` names only:
  `NEXT_PUBLIC_ELARA_MODE`, optional `NEXT_PUBLIC_SUPABASE_URL`, and optional
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- Privileged Lite values belong only in Vercel server-side environment variables:
  `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_LITE_SCHEMA`,
  `LITE_DEMO_ENABLED`, `LITE_MAX_QUERY_LENGTH`, `LITE_RETRIEVAL_LIMIT`,
  `LITE_MIN_SUPPORT_THRESHOLD`, and `LITE_CORPUS_VERSION`.
- `SUPABASE_SERVICE_ROLE_KEY`, `DEEPSEEK_API_KEY`, database URLs, Firebase Admin
  credentials, Redis, Celery, S3, Brave Search, Sentry auth, and tracing
  credentials must never be referenced from browser files or exposed through
  `NEXT_PUBLIC_*` names.

Lite Mode may store only the curated public-demo corpus and Lite demo run records
in Supabase. Supabase does not replace the Full Mode PostgreSQL/FastAPI
authorization boundary.

Curated corpus ingestion:

- Apply `infrastructure/lite/001_supabase_lite_schema.sql` in Supabase before
  loading seed data.
- Use the server-side web utility only for approved local fixtures:
  `npm --workspace @elara/web run lite:ingest -- --input fixtures/lite-corpus/seed-corpus.json`.
- Add `--dry-run` to validate chunking, hashing, and embedding mode without
  writing to Supabase.
- Add `--embedding-mode fixture` for deterministic credential-free tests or
  demos. Production/demo corpus refreshes should use the default `auto` mode,
  which calls the configured `DEEPSEEK_*` embedding route when
  `DEEPSEEK_EMBEDDING_MODEL` is present.
- Do not point Lite ingestion at arbitrary user uploads, live web crawls, or
  cached Full Mode reports. The cached response library remains deferred until
  Full Mode is completed and reviewed examples are captured.
