# Lite Mode deployment and portfolio runbook

Lite Mode is an additive public demo path for Elara.ai. It runs from the
Vercel-hosted Next.js app and queries a curated Supabase Postgres/pgvector corpus
through server-side routes and helpers. It is not the complete production verifier.

Full Mode remains the production architecture for verification work: Next.js calls
FastAPI, FastAPI enforces authentication and authorization, PostgreSQL/pgvector is
durable truth, Redis and Celery coordinate asynchronous work, the worker runs the
LangGraph-style workflow, Brave Search and private S3-compatible storage stay
server-side, and DeepSeek is called only through `DEEPSEEK_*` server configuration.

Lite Mode is the default public page at `/`. Full Mode remains reachable through
`/verify` and must be presented as the complete production verifier architecture,
not as the currently hosted public demo.

## Lite Mode versus Full Mode

Lite Mode:

- Runs on Vercel server-side routes and Supabase Postgres/pgvector.
- Retrieves from a curated stored evidence library only.
- Uses server-side DeepSeek for bounded language tasks and deterministic code for
  retrieval limits, thresholds, citation-presence checks, fallback decisions, and
  any scoring or arithmetic.
- Stores only Lite demo corpus metadata, chunks, demo runs, citations, feedback,
  and eval cases in Supabase.
- Does not perform live web search, uploaded-document verification, private
  source storage, Celery queue processing, or complete Full Mode report
  generation.

Full Mode:

- Runs through Next.js, FastAPI, PostgreSQL/pgvector, Redis, Celery workers,
  LangGraph-style workflow stages, Brave Search, private S3-compatible storage,
  Firebase Authentication, Sentry, tracing, and server-side DeepSeek.
- Remains paused after Step 25B staging evidence. The latest recorded staging
  state did not complete live-provider validation, migration/rollback rehearsal,
  queue recovery, credential rotation, alert delivery, or controlled live cases.
- Requires paid always-on infrastructure for the FastAPI API, Redis, Celery
  worker stack, PostgreSQL, private object storage, and related production
  services before production launch approval can be considered.

## Vercel project setup

1. Import the GitHub repository into Vercel.
2. Set the Vercel project root to `apps/web`.
3. Keep `/` as the Lite Mode entry route and keep `/verify` available for Full
   Mode.
4. Add only Lite-safe browser variables with `NEXT_PUBLIC_*` names.
5. Add privileged Supabase and DeepSeek values only as server-side Vercel
   environment variables.
6. Deploy Preview first, ingest a small corpus, run smoke prompts, then promote
   the same Git revision to Production.

Do not add Firebase Admin, PostgreSQL, Redis, Celery, S3, Brave Search,
DeepSeek, Supabase service-role, Sentry auth-token, or tracing credentials to any
browser-visible variable.

## Environment variables

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

Use these names in Vercel for Lite deployments:

```text
NEXT_PUBLIC_ELARA_MODE=lite
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_LITE_SCHEMA=public
LITE_DEMO_ENABLED=true
LITE_MAX_QUERY_LENGTH=1200
LITE_RETRIEVAL_LIMIT=8
LITE_MIN_SUPPORT_THRESHOLD=0.65
LITE_CORPUS_VERSION=lite-corpus-v1
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_CHAT_MODEL=deepseek-chat
DEEPSEEK_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_EMBEDDING_MODEL=
CITATION_REVISION_LIMIT=2
```

Leave `DEEPSEEK_EMBEDDING_MODEL` unset until an approved DeepSeek-compatible
embedding route is available. Credential-free tests and local demo ingestion may
use fixture embeddings, but the deployed public Lite demo should use the
configured server-side DeepSeek path when embeddings are available.

## Supabase pgvector setup

1. Create a Supabase project for Lite public-demo data only.
2. In the Supabase SQL editor, apply
   `infrastructure/lite/001_supabase_lite_schema.sql`.
3. Confirm the `vector` and `pgcrypto` extensions are enabled.
4. Confirm these tables exist: `lite_documents`, `lite_chunks`, `lite_runs`,
   `lite_run_citations`, `lite_feedback`, and `lite_eval_cases`.
5. Confirm `match_lite_chunks(...)` exists and is granted only to
   `service_role`.
6. Confirm row-level security is enabled. Browser users may read only the
   optional public document metadata view; evidence chunks, Lite runs, citations,
   feedback writes, and eval cases are server-side only.

Do not create or populate `lite_cached_responses` for Lite v1. Cached Full Mode
demo exemplars are deferred until Full Mode completion and review.

For the current Step 15 hosting attempt, blockers, smoke results, and remaining
commands are tracked in
[`infrastructure/lite/STEP_15_HOSTING_STATUS.md`](../../infrastructure/lite/STEP_15_HOSTING_STATUS.md).

## Curated corpus ingestion

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

Example dry run:

```powershell
npm --workspace @elara/web run lite:ingest -- --input fixtures/lite-corpus/seed-corpus.json --embedding-mode fixture --dry-run
```

Example Supabase write after the Lite Supabase env vars are configured:

```powershell
npm --workspace @elara/web run lite:ingest -- --input fixtures/lite-corpus/seed-corpus.json
```

## Public demo limitations

Use this copy when describing the hosted portfolio demo:

```text
Elara Lite is a public stored-corpus demo. It evaluates submitted claims or
questions only against a curated evidence library and returns cited,
timestamped, insufficient-evidence-aware answers. It is not the complete Elara
production verifier, does not search the live web, does not verify uploaded
private documents, and does not assign permanent credibility scores.
```

Every Lite report should preserve the product language boundary:

```text
Evidence reviewed as of [date and time]. New evidence or corrections may change this assessment.
```

## Deferred Full Mode response cache

Lite v1 ships without the cached Full Mode response library. The cache will be
populated only after Full Mode is completed, temporarily hosted, exercised with
controlled cases, and reviewed outputs are captured. Cached examples must be
labeled as reviewed demo examples, not newly generated live verification runs.

Temporary Full Mode capture checklist for that later phase:

- Architecture diagram showing Next.js, FastAPI, PostgreSQL/pgvector, Redis,
  Celery, worker, DeepSeek, Brave Search, private S3-compatible storage,
  Firebase Authentication, Sentry, and tracing boundaries.
- Queue and worker screenshots with all secrets, tokens, hostnames, internal
  identifiers, and private user content hidden.
- 10-20 high-quality completed Full Mode reports across the main supported use
  cases, each with reviewed citations and safe-to-publish evidence metadata.
- Smoke evidence for health checks, auth, queue admission, worker progress, SSE
  reconnect behavior, citation audit completion, and signed export behavior.
- Walkthrough video showing a controlled claim from submission through final
  cited report, with secrets and private evidence hidden.

Do not use this later checklist as evidence that Lite v1 has a cached response
library. It is a capture plan for after Full Mode completion.
