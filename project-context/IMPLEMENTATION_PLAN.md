# Elara.ai Implementation Plan

## Current Deployment Scope

Elara is a personal, low-traffic side project for owner-controlled demonstrations, not a production SaaS or public-service launch. `DEMO_SCOPE.md` is authoritative for deployment and completion scope. Prefer Vercel plus one AWS EC2 host and do not require high availability, multi-AZ services, autoscaling, separate staging/production infrastructure, formal on-call, or public-launch certification unless the user explicitly expands the project scope.

The product-correctness boundaries in this plan still apply: server-side credentials, non-public internal services, Firebase authorization, secure retrieval, deterministic scoring, PostgreSQL durability, and citation audit before completion.

Version: 1.1

Date: July 2026

Primary model provider: DeepSeek API  
Primary architecture sources:
- `docs/Elara.ai_Verification_and_Targeted_Retrieval_Methodology.pdf`
- `docs/Elara.ai_Web_Application_Architecture_and_Technical_Blueprint.pdf`

## 0. Architectural Guardrails

Elara.ai is an evidence-management and automated verification platform. It evaluates the evidence available for a specific claim, quotation, article, source document, or statement as of a specific retrieval timestamp. It must not present itself as an automatic lie detector, a permanent credibility score, or a general-purpose internet crawler.

The system boundaries are fixed:

- Frontend: Next.js App Router, TypeScript, React, Tailwind CSS, shadcn/ui, React Hook Form, Zod, TanStack Query, Zustand, React Flow, Recharts, Lucide React.
- Backend API: FastAPI, Python, Pydantic, SQLAlchemy, Alembic, Uvicorn, Server-Sent Events.
- Worker: Celery, Redis, LangGraph, DeepSeek API, structured Pydantic outputs, custom deterministic services.
- Retrieval and extraction: search API or model web search, httpx, Trafilatura, Beautiful Soup, Playwright fallback, PyMuPDF, pandas, dateparser.
- Numerical correctness: Python Decimal.
- Persistence: PostgreSQL, pgvector, Redis, S3-compatible object storage.
- Observability and evaluation: Sentry, LangSmith-compatible tracing where available, custom Python evaluators, GitHub Actions.
- Deployment: Vercel for Next.js, container hosting for FastAPI and Celery worker, managed PostgreSQL with pgvector, managed Redis, S3-compatible object storage.
- Authentication: Firebase Authentication for user identity, with Firebase Admin verification in FastAPI and PostgreSQL ownership records keyed by the Firebase user id.

Firebase authentication decision:

- Use the Firebase Web SDK only in the Next.js application for sign-in and sign-out.
- FastAPI is the authorization boundary. It verifies Firebase ID tokens or Firebase session cookies with the Firebase Admin SDK before loading or creating the PostgreSQL user.
- Store `auth_provider = "firebase"` and the Firebase `uid` as `auth_subject`; Firebase is not the application database.
- Do not use Firebase Hosting, Firestore, Realtime Database, Cloud Storage, Cloud Functions, or Firebase AI unless the architecture is explicitly expanded later.
- Do not expose `FIREBASE_CLIENT_EMAIL` or `FIREBASE_PRIVATE_KEY` to the browser.
- The Firebase Web configuration is public application metadata, but it does not replace backend authorization, ownership checks, or Firebase authorized-domain configuration.

DeepSeek provider decision:

- Use `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and explicit DeepSeek model names in server-side configuration.
- Do not expose DeepSeek credentials to the browser.
- Do not call OpenAI services.
- Do not use OpenAI environment variable names.
- Prefer a direct `httpx` DeepSeek client wrapper in the worker so provider ownership is explicit.
- DeepSeek's API is documented as API-format compatible with OpenAI and Anthropic, but Elara.ai should name the internal integration `DeepSeekClient` to avoid confusing provider boundaries.
- pgvector remains part of the architecture. Passage vector generation must use a DeepSeek-approved embedding path or a project-approved DeepSeek-compatible embedding endpoint. If embeddings are not available in the target DeepSeek account at implementation time, keep the pgvector schema and initially run lexical/metadata retrieval until the approved embedding route is confirmed.

The browser must never directly call DeepSeek, search providers, PostgreSQL, Redis, or object storage with privileged credentials. Every privileged action goes through FastAPI or the worker.

## 1. Repository Structure

Create the monorepo structure before building feature code:

```text
Elara.ai/
|-- apps/
|   |-- web/
|   |   |-- app/
|   |   |-- components/
|   |   |-- hooks/
|   |   |-- stores/
|   |   `-- lib/
|   |-- api/
|   |   |-- app/
|   |   |   |-- routes/
|   |   |   |-- auth/
|   |   |   |-- database/
|   |   |   |-- models/
|   |   |   |-- schemas/
|   |   |   `-- services/
|   |   `-- tests/
|   `-- worker/
|       |-- agents/
|       |-- graph/
|       |-- research/
|       |-- extraction/
|       |-- provenance/
|       |-- scoring/
|       |-- auditing/
|       `-- tasks/
|-- packages/
|   |-- api-client/
|   |-- shared-types/
|   `-- design-tokens/
|-- evals/
|-- infrastructure/
|-- docker-compose.yml
`-- IMPLEMENTATION_PLAN.md
```

Folder ownership:

- `apps/web`: browser routes, layouts, components, state, and API access.
- `apps/api`: FastAPI routes, authentication, validation, persistence, report reads, protected snapshot access.
- `apps/worker`: LangGraph workflow, DeepSeek calls, retrieval, extraction, provenance, scoring, audits.
- `packages/api-client`: generated or hand-written typed frontend client.
- `packages/shared-types`: shared enums, run states, report contracts.
- `packages/design-tokens`: color, spacing, typography, and interface tokens.
- `evals`: benchmark cases, graders, security fixtures, regression reports.
- `infrastructure`: containers, deployment files, environment configuration, CI/CD.

## 2. Phase 1: Infrastructure and Data Persistence

### 2.1 Local Development Infrastructure

Create `docker-compose.yml` for local development:

- PostgreSQL with pgvector enabled.
- Redis for Celery broker, cache, locks, rate limits, and progress streams.
- S3-compatible object storage service.
- FastAPI container.
- Celery worker container.
- Next.js development container or local Node workflow.

Environment separation:

- `.env.example` only contains placeholder names.
- Local-development and hosted-demo credentials are isolated.
- Secrets are loaded server-side only.
- Required model variables:
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL=https://api.deepseek.com`
  - `DEEPSEEK_CHAT_MODEL`
  - `DEEPSEEK_REASONING_MODEL`
  - `DEEPSEEK_EMBEDDING_MODEL`, only if the approved embedding route exists.

Firebase Authentication variables:

- Vercel/Next.js browser configuration:
  - `NEXT_PUBLIC_FIREBASE_API_KEY`
  - `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
  - `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
  - `NEXT_PUBLIC_FIREBASE_APP_ID`
- FastAPI server configuration:
  - `FIREBASE_PROJECT_ID`
  - `FIREBASE_CLIENT_EMAIL`
  - `FIREBASE_PRIVATE_KEY`

Deployment and service URL variables:

- Vercel receives `NEXT_PUBLIC_API_BASE_URL`, the four public Firebase values, and `NEXT_PUBLIC_SENTRY_DSN`.
- FastAPI receives `WEB_APP_URL`, `CORS_ALLOWED_ORIGINS`, Firebase Admin credentials, database/Redis/object-storage credentials, and `SENTRY_DSN_API`.
- The worker receives DeepSeek, search, database, Redis, object-storage, and `SENTRY_DSN_WORKER` credentials.
- Do not require `VERCEL_TOKEN`, Vercel project ids, container-registry credentials, or separate staging/production URL aliases for the default GitHub-connected demo flow.
- Local `.env.private` may contain real development credentials and must remain ignored. Commit only a placeholder-only `.env.example`.

### 2.2 PostgreSQL and Alembic Foundation

Initialize SQLAlchemy and Alembic in `apps/api/app/database`.

First Alembic migration:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
```

Use UUID primary keys, timezone-aware timestamps, explicit indexes, and enum types. Store durable workflow outputs in PostgreSQL. Redis data may expire because final status, report content, sources, passages, evidence, scores, and versions must be recoverable from PostgreSQL.

### 2.3 Core Enums

```text
RunStatus
- QUEUED
- VALIDATING
- DECOMPOSING
- RESEARCHING
- EXTRACTING
- ANALYZING_PROVENANCE
- SCORING
- SYNTHESIZING
- AUDITING
- COMPLETED
- FAILED
- CANCELLED

InputType
- CLAIM
- ARTICLE_URL
- ARTICLE_TEXT
- QUOTE
- PARAPHRASE
- UPLOADED_DOCUMENT

ResearchDepth
- QUICK
- STANDARD
- DEEP

SourceType
- PRIMARY
- OFFICIAL_SELF_REPORT
- INDEPENDENT_ANALYSIS
- SECONDARY_REPORT
- DERIVATIVE_REPORT
- OPINION
- UNKNOWN

AccessStatus
- PENDING
- FETCHED
- INACCESSIBLE
- PAYWALLED
- BOT_BLOCKED
- UNSUPPORTED
- FAILED

EvidenceStance
- STRONGLY_CONTRADICTS
- PARTIALLY_CONTRADICTS
- NEUTRAL
- PARTIALLY_SUPPORTS
- STRONGLY_SUPPORTS

DependencyRelationship
- CITES
- REPUBLISHES
- QUOTES
- DERIVES_FROM
- USES_SAME_DATA
- POSSIBLE_DUPLICATE
```

### 2.4 SQLAlchemy Data Model

#### users

Purpose: account identity, plan limits, ownership boundary.

Fields:

- `id uuid primary key`
- `auth_provider text not null`
- `auth_subject text not null`
- `email citext not null unique`
- `display_name text`
- `plan_tier text not null`
- `role text not null default 'user'`
- `usage_limits jsonb not null default '{}'`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`
- `deleted_at timestamptz`

Indexes:

- unique `(auth_provider, auth_subject)`
- unique `email`
- partial index on active users where `deleted_at is null`

#### verification_runs

Purpose: durable lifecycle record for each verification.

Fields:

- `id uuid primary key`
- `user_id uuid not null references users(id)`
- `input_type input_type not null`
- `research_depth research_depth not null`
- `status run_status not null`
- `submitted_text text`
- `submitted_url text`
- `upload_object_path text`
- `normalized_target jsonb not null default '{}'`
- `title text`
- `verdict text`
- `evidence_support int`
- `verdict_confidence int`
- `source_independence int`
- `context_completeness int`
- `methodology_version_id uuid references methodology_versions(id)`
- `workflow_version text not null`
- `model_versions jsonb not null default '{}'`
- `prompt_versions jsonb not null default '{}'`
- `parser_versions jsonb not null default '{}'`
- `queued_at timestamptz not null`
- `started_at timestamptz`
- `completed_at timestamptz`
- `failed_at timestamptz`
- `failure_code text`
- `failure_message text`
- `cancellation_requested_at timestamptz`
- `evidence_reviewed_at timestamptz`
- `visibility text not null default 'private'`
- `share_token_hash text`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Indexes:

- `(user_id, created_at desc)`
- `(status, queued_at)`
- `(visibility)`
- partial index on `share_token_hash` where not null

#### atomic_claims

Purpose: independently testable claim units.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `parent_claim_id uuid references atomic_claims(id)`
- `claim_text text not null`
- `normalized_claim text`
- `claim_type text not null`
- `importance_weight int not null`
- `entities jsonb not null default '[]'`
- `time_period text`
- `locations jsonb not null default '[]'`
- `metrics jsonb not null default '[]'`
- `comparison text`
- `ambiguities jsonb not null default '[]'`
- `fact_checkable boolean not null default true`
- `support_score int`
- `confidence_score int`
- `context_completeness int`
- `final_label text`
- `gates jsonb not null default '{}'`
- `created_at timestamptz not null`

Indexes:

- `(run_id, importance_weight desc)`
- GIN on `entities`
- GIN on `metrics`

#### search_queries

Purpose: auditable query planning record.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `atomic_claim_id uuid references atomic_claims(id) on delete cascade`
- `family text not null`
- `query_text text not null`
- `generated_by_node text not null`
- `priority numeric(6, 4)`
- `executed_at timestamptz`
- `result_count int`
- `created_at timestamptz not null`

Indexes:

- `(run_id, family)`
- `(atomic_claim_id, family)`

#### sources

Purpose: canonical source identity independent of any one run.

Fields:

- `id uuid primary key`
- `canonical_url text not null unique`
- `domain text not null`
- `title text`
- `author text`
- `publisher text`
- `source_type source_type not null default 'UNKNOWN'`
- `content_type text`
- `robots_or_policy_status text`
- `first_seen_at timestamptz not null`
- `last_seen_at timestamptz not null`

Indexes:

- unique `canonical_url`
- `(domain)`
- `(source_type)`

#### source_snapshots

Purpose: versioned fetched source content and extraction result.

Fields:

- `id uuid primary key`
- `source_id uuid not null references sources(id) on delete cascade`
- `retrieved_at timestamptz not null`
- `published_at timestamptz`
- `updated_at timestamptz`
- `access_status access_status not null`
- `content_hash text`
- `snapshot_path text`
- `parser_name text`
- `parser_version text`
- `extraction_quality numeric(6, 4)`
- `correction_status text`
- `metadata jsonb not null default '{}'`
- `failure_reason text`
- `created_at timestamptz not null`

Indexes:

- `(source_id, retrieved_at desc)`
- `(content_hash)`
- `(access_status)`

Rules:

- Changed content creates a new snapshot.
- Earlier reports continue referencing the exact snapshot they analyzed.
- Store content hash, retrieval time, parser name/version, and exact evidence excerpts included in reports.

#### run_sources

Purpose: source selection record for a specific run.

Fields:

- `run_id uuid references verification_runs(id) on delete cascade`
- `source_id uuid references sources(id) on delete cascade`
- `snapshot_id uuid references source_snapshots(id)`
- `role text not null`
- `retrieval_reason text`
- `priority_score numeric(6, 4)`
- `selected_rank int`
- `inaccessible_reason text`
- `created_at timestamptz not null`

Primary key:

- `(run_id, source_id)`

#### source_passages

Purpose: exact passage, page, section, speaker, table row, and vector traceability.

Fields:

- `id uuid primary key`
- `snapshot_id uuid not null references source_snapshots(id) on delete cascade`
- `source_id uuid not null references sources(id) on delete cascade`
- `text text not null`
- `text_hash text not null`
- `heading_path text`
- `page_or_position text`
- `paragraph_index int`
- `speaker text`
- `table_ref text`
- `embedding vector(1536)`
- `embedding_model text`
- `extraction_certainty numeric(6, 4) not null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz not null`

Indexes:

- `(source_id)`
- `(snapshot_id)`
- `(text_hash)`
- vector index after the table has meaningful volume.

Notes:

- Use the actual dimension required by the approved DeepSeek embedding route.
- If the embedding dimension differs from 1536, update the Alembic migration before deploying that embedding route.
- Do not detach embeddings from passage ids; every vector result must resolve to exact source text.

#### evidence_items

Purpose: claim-to-passage relationship and scoring inputs.

Fields:

- `id uuid primary key`
- `atomic_claim_id uuid not null references atomic_claims(id) on delete cascade`
- `passage_id uuid not null references source_passages(id) on delete cascade`
- `stance evidence_stance not null`
- `stance_value numeric(4, 2) not null`
- `relevance numeric(6, 4) not null`
- `directness numeric(6, 4) not null`
- `authority numeric(6, 4) not null`
- `transparency numeric(6, 4) not null`
- `temporal_fit numeric(6, 4) not null`
- `extraction_certainty numeric(6, 4) not null`
- `base_quality numeric(8, 6) not null`
- `dependency_multiplier numeric(6, 4) not null`
- `adjusted_weight numeric(8, 6) not null`
- `rejection_reason text`
- `citation_status text not null default 'pending'`
- `created_at timestamptz not null`

Indexes:

- `(atomic_claim_id)`
- `(passage_id)`
- `(stance)`

#### information_clusters

Purpose: source independence and derivative reporting grouping.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `label text not null`
- `origin_type text`
- `representative_source_id uuid references sources(id)`
- `created_at timestamptz not null`

Indexes:

- `(run_id)`

#### source_dependencies

Purpose: provenance graph.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `parent_source_id uuid not null references sources(id)`
- `child_source_id uuid not null references sources(id)`
- `relationship dependency_relationship not null`
- `confidence numeric(6, 4) not null`
- `detection_method text not null`
- `information_cluster_id uuid references information_clusters(id)`
- `created_at timestamptz not null`

Indexes:

- `(run_id)`
- `(parent_source_id)`
- `(child_source_id)`
- unique `(run_id, parent_source_id, child_source_id, relationship)`

#### calculations

Purpose: reproducible deterministic math audit trail.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `atomic_claim_id uuid references atomic_claims(id) on delete cascade`
- `formula_name text not null`
- `formula_text text not null`
- `inputs jsonb not null`
- `result jsonb not null`
- `units text`
- `decimal_context jsonb not null`
- `audit_status text not null`
- `created_at timestamptz not null`

Indexes:

- `(run_id, formula_name)`
- `(atomic_claim_id)`

#### agent_events

Purpose: durable public workflow event log. Do not store private chain-of-thought.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `sequence int not null`
- `stage run_status not null`
- `event_type text not null`
- `public_message text not null`
- `payload jsonb not null default '{}'`
- `created_at timestamptz not null`

Indexes:

- unique `(run_id, sequence)`
- `(run_id, created_at)`

#### report_citations

Purpose: sentence-to-passage citation audit.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `atomic_claim_id uuid references atomic_claims(id)`
- `report_section text not null`
- `sentence_text text not null`
- `passage_id uuid not null references source_passages(id)`
- `audit_status text not null`
- `audit_note text`
- `created_at timestamptz not null`

Indexes:

- `(run_id, report_section)`
- `(passage_id)`

#### user_feedback

Purpose: corrections, missed evidence, appeals, and broken citation reports.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `user_id uuid not null references users(id)`
- `category text not null`
- `message text not null`
- `source_url text`
- `status text not null default 'open'`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Indexes:

- `(run_id, created_at desc)`
- `(status)`

#### methodology_versions

Purpose: immutable methodology and scoring configuration.

Fields:

- `id uuid primary key`
- `version text not null unique`
- `scoring_config jsonb not null`
- `retrieval_config jsonb not null`
- `released_at timestamptz not null`
- `active boolean not null default false`

#### exports

Purpose: generated reports and data exports.

Fields:

- `id uuid primary key`
- `run_id uuid not null references verification_runs(id) on delete cascade`
- `export_type text not null`
- `object_path text not null`
- `content_hash text not null`
- `created_at timestamptz not null`

Indexes:

- `(run_id, export_type, created_at desc)`

### 2.5 pgvector Setup

Implementation steps:

1. Enable pgvector in the first migration.
2. Add `embedding vector(N)` to `source_passages`.
3. Store `embedding_model` per passage.
4. Store model versions on each run.
5. Add an HNSW or IVFFLAT cosine index after the table contains enough passages to tune index parameters.
6. Build retrieval queries that combine:
   - vector similarity,
   - lexical match,
   - exact quotation or identifier match,
   - metadata fit for entity/date/location/document type,
   - source role and extraction certainty.

Important constraint:

- Vector search is retrieval assistance, not truth scoring.
- Evidence support is calculated only after evidence stance, quality, dependency multipliers, and rejection gates are applied.

### 2.6 Redis Setup

Use Redis for transient data only.

Celery:

```text
broker_url = redis://...
result_backend = redis://...
queues:
- verification.quick
- verification.standard
- verification.deep
```

Progress events:

```text
elara:run:{run_id}:events
```

Use Redis Streams for progress because they support replay with `Last-Event-ID`.

Fetch locks:

```text
elara:lock:fetch:{canonical_url_hash}
elara:lock:run:{run_id}
```

Rate limits:

```text
elara:rl:user:{user_id}
elara:rl:ip:{ip_hash}
elara:rl:domain:{domain}
```

Cache keys:

```text
elara:cache:source:{canonical_url_hash}:{revision_hash}
elara:cache:search:{query_hash}
elara:cache:extract:{content_hash}:{parser_version}
```

TTL policy:

- Stable filings: long TTL.
- News pages: medium TTL.
- Live blogs and APIs: short TTL.
- Failed or inaccessible source attempts: short cooldown TTL.

### 2.7 S3-Compatible Object Storage

Object paths:

```text
uploads/{user_id}/{run_id}/{upload_id}/original
snapshots/{domain}/{yyyy}/{mm}/{source_id}/{snapshot_id}/raw
snapshots/{domain}/{yyyy}/{mm}/{source_id}/{snapshot_id}/extracted.json
evidence/{run_id}/{snapshot_id}/included-passages.json
exports/{user_id}/{run_id}/report.json
exports/{user_id}/{run_id}/report.pdf
```

Object metadata:

- `run_id`
- `source_id`
- `snapshot_id`
- `content_hash`
- `retrieved_at`
- `parser_name`
- `parser_version`
- `content_type`

Rules:

- Store only permitted snapshots.
- Store exact included evidence excerpts even when full snapshots are not stored.
- Do not overwrite snapshots.
- Never expose permanent object-storage URLs.
- FastAPI issues short-lived signed URLs only after authorization.

## 3. Phase 2: API and Asynchronous Boundaries

### 3.1 FastAPI Route Groups

Core API routes:

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
POST   /v1/uploads
GET    /v1/verifications/{run_id}/exports/{export_id}
POST   /v1/verifications/{run_id}/exports
POST   /v1/auth/session
DELETE /v1/auth/session
```

API responsibilities:

- Authenticate every protected request.
- Determine the current user.
- Validate input sizes, file types, URLs, research depth, and account limits.
- Create, cancel, retry, save, export, share, and delete verification runs.
- Issue short-lived access to permitted snapshots and exports.
- Read durable report data from PostgreSQL.
- Read transient progress from Redis.
- Return stable, versioned response schemas.

Firebase Authentication contract:

1. Next.js signs the user in with the Firebase Web SDK.
2. For normal API requests, the browser sends the current Firebase ID token in `Authorization: Bearer <token>`.
3. FastAPI verifies the token with the Firebase Admin SDK, reads the Firebase `uid`, and loads or creates the corresponding PostgreSQL `users` row.
4. `POST /v1/auth/session` verifies a fresh Firebase ID token and exchanges it for a short-lived Firebase session cookie used by credentialed SSE connections.
5. The session cookie must be `HttpOnly` and `Secure`. Prefer `app.example.com` and `api.example.com` so `SameSite=Lax` works; use `SameSite=None` only when the frontend and API must remain cross-site.
6. `DELETE /v1/auth/session` clears the session cookie. Revocation-sensitive operations may additionally check Firebase token or session revocation.
7. CORS must allow only configured frontend origins and credentials. Never put an ID token or session token in a URL query string.

Firebase configuration rules:

- Enable only the selected Firebase Authentication sign-in providers.
- Add `localhost`, the Vercel production domain, approved Vercel preview domains where needed, and the custom application domain to Firebase Authorized domains.
- The Firebase Admin private key is server-only and must preserve its newline characters when loaded from an environment variable.
- Firebase authenticates identity; FastAPI and PostgreSQL continue to enforce run, source, snapshot, export, feedback, and sharing authorization.

### 3.2 Pydantic Request and Response Schemas

Create schemas in `apps/api/app/schemas`.

```python
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, AnyHttpUrl, model_validator


class InputType(StrEnum):
    CLAIM = "CLAIM"
    ARTICLE_URL = "ARTICLE_URL"
    ARTICLE_TEXT = "ARTICLE_TEXT"
    QUOTE = "QUOTE"
    PARAPHRASE = "PARAPHRASE"
    UPLOADED_DOCUMENT = "UPLOADED_DOCUMENT"


class ResearchDepth(StrEnum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    DECOMPOSING = "DECOMPOSING"
    RESEARCHING = "RESEARCHING"
    EXTRACTING = "EXTRACTING"
    ANALYZING_PROVENANCE = "ANALYZING_PROVENANCE"
    SCORING = "SCORING"
    SYNTHESIZING = "SYNTHESIZING"
    AUDITING = "AUDITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationCreateRequest(BaseModel):
    input_type: InputType
    research_depth: ResearchDepth = ResearchDepth.STANDARD
    text: str | None = Field(default=None, max_length=50_000)
    url: AnyHttpUrl | None = None
    quote: str | None = Field(default=None, max_length=10_000)
    speaker: str | None = Field(default=None, max_length=500)
    upload_id: UUID | None = None

    @model_validator(mode="after")
    def validate_input_payload(self) -> "VerificationCreateRequest":
        if self.input_type in {InputType.CLAIM, InputType.ARTICLE_TEXT, InputType.PARAPHRASE} and not self.text:
            raise ValueError("text is required for this input type")
        if self.input_type == InputType.ARTICLE_URL and not self.url:
            raise ValueError("url is required for ARTICLE_URL")
        if self.input_type == InputType.QUOTE and not self.quote:
            raise ValueError("quote is required for QUOTE")
        if self.input_type == InputType.UPLOADED_DOCUMENT and not self.upload_id:
            raise ValueError("upload_id is required for UPLOADED_DOCUMENT")
        return self


class VerificationCreateResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    events_url: str
    report_url: str | None = None


class ProgressEvent(BaseModel):
    run_id: UUID
    stage: RunStatus
    message: str
    completed_steps: int
    total_steps: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    inaccessible_count: int = 0
    created_at: datetime


class ScoreBundle(BaseModel):
    evidence_support: int | None = None
    attribution_support: int | None = None
    quote_fidelity: int | None = None
    verdict_confidence: int | None = None
    source_independence: int | None = None
    context_completeness: int | None = None


class AtomicClaimResponse(BaseModel):
    id: UUID
    claim_text: str
    importance_weight: int
    claim_type: str
    final_label: str | None
    support_score: int | None
    confidence_score: int | None
    context_completeness: int | None
    ambiguities: list[str]
    gaps: list[str]


class EvidenceItemResponse(BaseModel):
    id: UUID
    atomic_claim_id: UUID
    passage_id: UUID
    stance: str
    base_quality: float
    dependency_multiplier: float
    adjusted_weight: float
    citation_status: str
    passage_text: str
    source_title: str | None
    source_url: str
    page_or_position: str | None


class SourceGraphNode(BaseModel):
    id: str
    type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship: str
    confidence: float


class SourceGraphResponse(BaseModel):
    nodes: list[SourceGraphNode]
    edges: list[SourceGraphEdge]


class CalculationResponse(BaseModel):
    id: UUID
    formula_name: str
    formula_text: str
    inputs: dict[str, Any]
    result: dict[str, Any]
    units: str | None
    audit_status: str


class ReportResponse(BaseModel):
    run_id: UUID
    verdict: str | None
    scores: ScoreBundle
    atomic_claims: list[AtomicClaimResponse]
    evidence: list[EvidenceItemResponse]
    source_graph: SourceGraphResponse
    calculations: list[CalculationResponse]
    methodology_version: str
    evidence_reviewed_at: datetime
    limitations: list[str]
```

### 3.3 Creating a Verification Run

FastAPI flow for `POST /v1/verifications`:

1. Authenticate user.
2. Validate request using Pydantic.
3. Check account plan and research-depth limits.
4. Validate submitted URL using lightweight URL rules before queueing.
5. Insert `verification_runs` with `QUEUED`.
6. Insert first `agent_events` record.
7. Commit transaction.
8. Queue Celery task with `run_id`.
9. Return `202 Accepted` with `run_id` and `events_url`.

Do not perform retrieval, model calls, PDF parsing, browser rendering, or scoring inside the request-response cycle.

### 3.4 Celery Integration

Celery task signature:

```python
@celery_app.task(
    name="verification.verify_run",
    bind=True,
    autoretry_for=(TransientProviderError, TransientFetchError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def verify_run(self, run_id: str) -> None:
    ...
```

Task routing:

- `QUICK` -> `verification.quick`
- `STANDARD` -> `verification.standard`
- `DEEP` -> `verification.deep`

Worker rules:

- Load durable run state from PostgreSQL.
- Transition status durably at every major stage.
- Write public progress to Redis Stream.
- Mirror public progress to `agent_events`.
- Check cancellation before expensive operations.
- Mark `FAILED` with a concise public failure code and message.
- Do not expose private reasoning traces in `agent_events`.

### 3.5 Server-Sent Events

Route:

```text
GET /v1/verifications/{run_id}/events
```

Architecture:

- Authenticates with the Firebase session cookie and authorizes the run against PostgreSQL ownership or share policy.
- Uses `StreamingResponse` with `text/event-stream`.
- Reads Redis Stream `elara:run:{run_id}:events`.
- Supports `Last-Event-ID` for reconnect replay.
- Sends heartbeat comments every 15-30 seconds.
- Ends after `COMPLETED`, `FAILED`, or `CANCELLED`.
- The browser opens the stream with credentials enabled. Firebase tokens must never be placed in the SSE URL.

Example event:

```text
event: progress
id: 1700000000-0
data: {
  "run_id": "run_123",
  "stage": "EXTRACTING",
  "message": "Extracted 9 of 12 candidate sources",
  "completed_steps": 4,
  "total_steps": 9
}
```

Reliability rule:

- Progress events are informative, not authoritative.
- Final status and report content must always reload from PostgreSQL.

## 4. Phase 3: Verification Worker and LangGraph Workflow

### 4.1 Worker Package Layout

```text
apps/worker/
|-- agents/
|   |-- intake.py
|   |-- decomposition.py
|   |-- planning.py
|   |-- evidence_classification.py
|   |-- synthesis.py
|   `-- citation_audit.py
|-- graph/
|   |-- state.py
|   |-- workflow.py
|   `-- transitions.py
|-- research/
|   |-- search.py
|   |-- ranking.py
|   |-- url_guard.py
|   |-- fetcher.py
|   `-- cache.py
|-- extraction/
|   |-- html_trafilatura.py
|   |-- html_bs4.py
|   |-- browser_playwright.py
|   |-- pdf_pymupdf.py
|   |-- tables.py
|   `-- passages.py
|-- provenance/
|   |-- dependencies.py
|   |-- clustering.py
|   `-- graph_export.py
|-- scoring/
|   |-- evidence_quality.py
|   |-- factual_support.py
|   |-- confidence.py
|   |-- independence.py
|   |-- quote_fidelity.py
|   |-- context.py
|   `-- labels.py
|-- auditing/
|   |-- numerical.py
|   |-- citations.py
|   `-- security.py
`-- tasks/
    `-- verification.py
```

### 4.2 DeepSeek Client

Create a dedicated provider module:

```text
apps/worker/agents/deepseek_client.py
```

Responsibilities:

- Read DeepSeek configuration from server-side environment.
- Use `httpx.AsyncClient`.
- Support structured JSON outputs.
- Support streaming only when useful internally; user-facing live progress comes from Redis/SSE, not raw model tokens.
- Record model name, prompt version, temperature, response ids where available, token usage, latency, and provider errors.
- Redact prompts and retrieved private content from logs.

Model usage:

- Intake and classification: non-reasoning chat model.
- Decomposition and planning: chat or reasoning model depending on complexity.
- Evidence classification: structured output with low temperature.
- Synthesis: evidence-grounded generation with strict citation requirements.
- Auditor: structured output with sentence-to-passage validation.

### 4.3 LangGraph State

Create `apps/worker/graph/state.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NormalizedInput(BaseModel):
    input_type: str
    text: str | None = None
    url: str | None = None
    quote: str | None = None
    speaker: str | None = None
    upload_object_path: str | None = None
    detected_language: str | None = None


class ResearchObjective(BaseModel):
    atomic_claim_id: UUID | None
    family: str
    objective: str
    required_source_role: str | None = None
    priority: float


class SearchQueryState(BaseModel):
    family: str
    query_text: str
    atomic_claim_id: UUID | None
    priority: float


class CandidateSource(BaseModel):
    url: str
    canonical_url: str
    title: str | None = None
    snippet: str | None = None
    domain: str
    priority_score: float
    retrieval_reason: str


class WorkflowError(BaseModel):
    stage: str
    code: str
    message: str
    recoverable: bool = True


class VerificationState(BaseModel):
    run_id: UUID
    user_id: UUID
    input: NormalizedInput
    research_depth: str
    methodology_version: str
    started_at: datetime
    claims: list[dict] = Field(default_factory=list)
    objectives: list[ResearchObjective] = Field(default_factory=list)
    queries: list[SearchQueryState] = Field(default_factory=list)
    candidate_sources: list[CandidateSource] = Field(default_factory=list)
    snapshots: list[dict] = Field(default_factory=list)
    passages: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    dependencies: list[dict] = Field(default_factory=list)
    calculations: list[dict] = Field(default_factory=list)
    scores: dict | None = None
    report_draft: dict | None = None
    citation_audit: dict | None = None
    errors: list[WorkflowError] = Field(default_factory=list)
```

### 4.4 LangGraph Nodes

#### Intake

Responsibilities:

- Normalize input.
- Classify accepted input type.
- Identify speaker, entities, dates, locations, metrics, definitions, comparisons, venue, ambiguities.
- Separate verifiable fact, attribution, quote, paraphrase, allegation, prediction, opinion, rhetorical framing.
- Persist normalized target to `verification_runs.normalized_target`.

DeepSeek usage:

- Structured extraction and classification.

Deterministic controls:

- Input-size validation.
- URL normalization.
- Upload type checks.
- Date parsing with dateparser after model extraction.

#### Decomposition

Responsibilities:

- Split complex statements into atomic claims.
- Assign importance weights:
  - Essential: 3
  - Major: 2
  - Minor: 1
- Preserve original text span.
- Exclude predictions and opinions from factual scoring while keeping them in the report as labeled content.

DeepSeek usage:

- Atomic claim decomposition and importance rationale in structured output.

Deterministic controls:

- Valid importance range.
- Deduplicate equivalent claims.
- Enforce maximum claim count based on research depth.

#### Planner

Responsibilities:

- Generate search objectives and query families:
  - primary source,
  - supporting evidence,
  - counterevidence,
  - definition,
  - context,
  - attribution,
  - existing fact check,
  - historical context.
- Preserve exact quotations in at least one attribution query.
- Create neutral and contradiction-oriented queries that do not assume the submitted claim is true.
- Persist every query to `search_queries`.

DeepSeek usage:

- Query generation and objective planning.

Deterministic controls:

- Query count by research depth.
- Required query families by claim type.
- Exact quote preservation.

Research depth defaults:

```text
QUICK
- 4-6 sources
- one query round
- no browser fallback unless essential

STANDARD
- 8-12 sources
- support and contradiction paths
- limited fallback

DEEP
- 15-30 sources
- broader provenance
- multiple primary-source attempts
```

#### Discovery and Source Selection

Responsibilities:

- Use search API or model web search.
- Canonicalize candidate URLs.
- Deduplicate before fetch.
- Rank candidates.
- Reserve source slots for primary evidence.
- Reserve separate slots for supporting and contradicting evidence.
- Limit pages from one domain or obvious content cluster.

Retrieval priority formula:

```text
priority = 0.30R + 0.20D + 0.15T + 0.15V + 0.10N + 0.10E
```

Where:

- `R`: claim relevance.
- `D`: source directness.
- `T`: temporal fit.
- `V`: source-type diversity.
- `N`: novelty.
- `E`: extractability.

This score predicts usefulness and extractability. It is not a truth score.

#### Secure Retrieval

Responsibilities:

- Fetch only selected public sources.
- Enforce URL and network security.
- Reuse recent source snapshots when allowed.
- Store inaccessible sources explicitly.

URL and network controls:

- Accept HTTP and HTTPS only.
- Reject localhost, private networks, link-local ranges, reserved addresses, and cloud metadata endpoints.
- Re-resolve DNS at connection time to reduce DNS rebinding risk.
- Limit redirects and revalidate every destination.
- Restrict ports to approved web ports unless explicitly configured.
- Reject executable or unsupported response types.
- Abort responses exceeding configured content-type size limits.
- Use connection, read, and total request deadlines.
- Apply per-domain and per-user limits.
- Never forward user authentication cookies or private provider credentials to third-party sites.
- Store fetched files outside executable paths and never launch them.

Default operational policies:

- Redirect limit: 3.
- Static request timeout: 10-20 seconds total.
- Network retries: 1-2 for transient failures.
- Playwright retries: maximum one per important source.
- Search broadening: maximum one additional round in Standard mode.
- Inaccessible source: record explicit status; never represent as verified.

#### Extraction

Fallback order:

1. `httpx` plus Trafilatura.
2. Beautiful Soup custom extraction.
3. Playwright rendered page.
4. PyMuPDF for PDFs.
5. Mark inaccessible and continue with alternatives.

Extraction outputs:

- title,
- author,
- publisher,
- publication date,
- update date,
- retrieval date,
- article body,
- headings,
- tables,
- quotes,
- correction notices,
- outbound links,
- page or section positions,
- content hash,
- parser name and version,
- extraction quality score.

Extraction quality checks:

- Minimum readable-text length after boilerplate removal.
- Title and body consistency.
- Duplicate-line and navigation-noise ratio.
- Presence of searched entities, dates, quotations, or claim terms.
- Detection of truncation, access barriers, malformed tables, hidden content.

Playwright restrictions:

- Static extraction must be attempted first.
- Use only when client-side rendering is necessary and the source is important enough.
- Disable unnecessary media and third-party requests.
- Enforce navigation timeout and DOM-size limits.
- Never expose provider keys, internal cookies, or privileged browser sessions.

#### Passage Segmentation and Embedding

Responsibilities:

- Segment by headings, paragraphs, transcript turns, table rows, and semantic boundaries.
- Use limited overlap.
- Preserve page number, heading path, paragraph order, and source identifier.
- Keep quotations attached to speaker and surrounding text.
- Keep table values attached to row and column labels.
- Generate embeddings only through the approved DeepSeek-compatible embedding path.
- Store exact text and embedding on `source_passages`.

Passage relevance combines:

- lexical score,
- semantic similarity,
- metadata fit,
- reranker score where implemented.

Exact matching is strongest for names, quotations, numbers, and identifiers.

#### Provenance and Source Dependency Analysis

Responsibilities:

- Trace information origins.
- Group derivative reporting.
- Detect explicit citations and outbound links.
- Detect syndication, near-identical text, shared quotations, shared statistics, shared tables, shared errors.
- Use publication timestamps and first-known appearance.

Relationships:

- `CITES`
- `REPUBLISHES`
- `QUOTES`
- `DERIVES_FROM`
- `USES_SAME_DATA`
- `POSSIBLE_DUPLICATE`

Dependency multipliers:

```text
Original or genuinely independent evidence: 1.00
Meaningful independent analysis using same chain: 0.35
Mostly repeated reporting or second-hand retelling: 0.10
Exact syndicated or copied version: 0.00
```

#### Evidence Classification

Responsibilities:

- Assign stance:
  - strongly contradicts: -1.00
  - partially contradicts: -0.50
  - neutral or irrelevant: 0.00
  - partially supports: +0.50
  - strongly supports: +1.00
- Assign evidence quality dimensions:
  - relevance,
  - directness,
  - claim-specific authority,
  - transparency,
  - temporal fit,
  - extraction certainty.

DeepSeek usage:

- Semantic classification of passage relationship to claim.
- Extraction of explicit support, contradiction, uncertainty, omitted context.

Deterministic rejection gates:

- Relevance below 0.50.
- Extraction certainty below 0.65.
- Wrong person, organization, event, location, or time period.
- Quotation or number cannot be located in the cited source.
- Page discusses the controversy but supplies no evidence for the exact claim.

#### Scoring

Use deterministic Python services only.

Evidence-item quality:

```text
q_i = 0.25R + 0.20D + 0.20A + 0.15T + 0.10F + 0.10X
```

Adjusted evidence weight:

```text
w_i = q_i * dependency_multiplier
```

Supporting weight:

```text
P = sum(max(stance_i, 0) * w_i)
```

Contradicting weight:

```text
N = sum(max(-stance_i, 0) * w_i)
```

Evidence support:

```text
100 * P / (P + N)
```

Evidence consistency:

```text
100 * abs(P - N) / (P + N)
```

Verdict confidence:

```text
base = 0.30COV + 0.25QUAL + 0.20IND + 0.15CONS + 0.10PRI
confidence = clamp(base - penalties, 0, 100)
```

Source independence:

```text
0.40O + 0.25P + 0.20G + 0.15M
```

Quote fidelity:

```text
0.35 wording
+ 0.20 speaker identity
+ 0.20 completeness
+ 0.15 sequence integrity
+ 0.10 translation accuracy
```

When translation is not applicable, omit its weight and normalize the others.

Context completeness:

```text
clamp(100 - sum(material penalties), 0, 100)
```

Article factual accuracy:

```text
sum(atomic_claim_support * importance_weight) / sum(importance_weight)
```

Essential-claim gate:

- If an essential claim is strongly refuted with adequate confidence, the article cannot receive a fully supported assessment even if minor claims are accurate.

Insufficient-evidence gate:

- Total adjusted evidence is below configured minimum.
- No essential claim has adequate evidence.
- Only information comes from one interested source and cannot be independently checked.
- Key definitions, dates, or identities cannot be resolved.

#### Numerical Audit

Use Python Decimal for:

- percentages,
- ratios,
- totals,
- comparisons,
- unit conversions,
- denominators,
- reporting periods.

Store every reproducible calculation in `calculations`.

Do not let DeepSeek perform final arithmetic. The model may identify candidate values and formulas, but deterministic code validates and computes.

#### Synthesis

Responsibilities:

- Generate a report from approved evidence only.
- Show strongest credible contradiction.
- Distinguish not verified from false.
- Distinguish attribution from factual content.
- Label predictions, opinions, allegations, unresolved causation, and disputed attribution.
- Include limitations and inaccessible sources.
- Include the required evidence timestamp:

```text
Evidence reviewed as of [date and time]. New evidence or corrections may change this assessment.
```

Product language rule:

- Evaluate only the submitted claim, quotation, article, or statement.
- Do not assign permanent honesty, credibility, or trustworthiness scores to people, companies, groups, or publications.

#### Citation Audit

Responsibilities:

- Split generated report into factual sentences.
- Verify every factual sentence has a citation.
- Verify the cited passage supports the sentence.
- Reject unsupported claims.
- Require revision before marking run `COMPLETED`.

DeepSeek usage:

- Sentence-to-passage entailment checks in structured output.

Deterministic controls:

- Citation presence.
- Passage id existence.
- Source ownership and access.
- No citation to rejected evidence.

### 4.5 Prompt-Injection Boundary

Retrieved pages are evidence, not instructions.

Any source text that says to ignore instructions, change behavior, reveal secrets, browse private data, alter scores, or override system policy must be stored as source content only. It must never modify:

- system prompts,
- tool permissions,
- URL policy,
- credential handling,
- scoring formulas,
- final verdict logic.

## 5. Phase 4: Frontend Application

### 5.1 Next.js App Router Structure

```text
apps/web/app/
|-- layout.tsx
|-- page.tsx
|-- methodology/
|   `-- page.tsx
|-- verify/
|   |-- page.tsx
|   `-- [runId]/
|       `-- page.tsx
|-- report/
|   `-- [runId]/
|       `-- page.tsx
|-- history/
|   `-- page.tsx
|-- saved/
|   `-- page.tsx
|-- settings/
|   `-- page.tsx
`-- api/
```

Layout strategy:

- Root layout: Firebase Auth provider, TanStack Query provider, global styles, and metadata.
- Public layout: landing and methodology pages.
- Authenticated app layout: navigation, account shell, query provider, workspace frame.
- Report layout: report header, source drawer slot, responsive panel layout.

### 5.2 Frontend State Strategy

Use TanStack Query for server-owned data:

```text
["run", runId]
["report", runId]
["sources", runId]
["source-graph", runId]
["history", filters]
["exports", runId]
```

Use mutations for:

- create verification,
- cancel run,
- retry run,
- submit feedback,
- create export,
- save report,
- delete run.

Use Zustand only for transient UI state:

```text
selectedClaimId
selectedSourceId
selectedEvidenceId
activeReportTab
evidenceFilter
sourceDrawerOpen
graphLayoutMode
workspacePanelSizes
```

Do not duplicate reports in Zustand. The canonical report lives in PostgreSQL and is fetched through FastAPI.

Only non-sensitive UI preferences may be persisted in localStorage.

### 5.3 Forms and Validation

Use React Hook Form plus Zod.

Submission modes:

- plain claim,
- article URL,
- pasted article,
- quote,
- paraphrase,
- uploaded document.

Validation:

- required field by input type,
- max text length,
- URL syntax,
- file type and size,
- research depth,
- speaker field when useful for quote workflows.

FastAPI remains the final validation authority.

### 5.4 Real-Time UI

Create `useRunEvents(runId)`:

- Opens EventSource to `/v1/verifications/{run_id}/events`.
- Handles progress events.
- Handles reconnect.
- Tracks last event id where browser support allows.
- Invalidates TanStack Query caches when terminal status appears.
- Falls back to polling `GET /v1/verifications/{run_id}` when SSE fails repeatedly.

Live research view:

- current run state,
- completed steps,
- total steps,
- source counts,
- inaccessible source notices,
- cancellation control,
- time elapsed,
- latest public event message.

Never show hidden chain-of-thought or private reasoning transcripts.

### 5.5 Report Workspace

Desktop layout:

- left rail: atomic claims and filters,
- center: report overview and evidence panels,
- right drawer: source passage, metadata, snapshot, citation details.

Mobile layout:

- tabs for overview, claims, evidence, graph, calculations, methodology.
- source drawer as full-screen or bottom sheet.

Report sections:

- Overview with verdict, score roles, summary, limitations, evidence timestamp.
- Atomic claim cards with individual labels, support, confidence, importance, and gaps.
- Attribution panel when applicable.
- Quote fidelity and surrounding context panels when applicable.
- Side-by-side supporting and contradicting evidence.
- Source-dependency graph.
- Numerical audit.
- Methodology and version information.
- Feedback and correction controls.

### 5.6 React Flow Source Graph

Nodes:

- source,
- snapshot,
- information cluster,
- dataset,
- filing,
- transcript,
- recording,
- report.

Edges:

- CITES,
- REPUBLISHES,
- QUOTES,
- DERIVES_FROM,
- USES_SAME_DATA,
- POSSIBLE_DUPLICATE.

Interactions:

- Click node to open source drawer.
- Click edge to show relationship, confidence, and detection method.
- Filter by atomic claim, relationship, source role, access status, and cluster.
- Highlight evidence used in the final report.

Graph data comes from:

```text
GET /v1/verifications/{run_id}/source-graph
```

### 5.7 Recharts Visualizations

Charts:

- Score breakdown:
  - Evidence Support,
  - Attribution Support,
  - Quote Fidelity,
  - Verdict Confidence,
  - Source Independence,
  - Context Completeness.
- Evidence balance:
  - supporting adjusted weight vs contradicting adjusted weight per claim.
- Confidence components:
  - coverage,
  - average quality,
  - source independence,
  - evidence consistency,
  - primary-source access,
  - penalties.
- Research coverage:
  - adequate evidence,
  - insufficient evidence,
  - inaccessible source impact.
- Numerical audit:
  - claimed value vs source value,
  - units,
  - denominator,
  - period.

All chart data must come from deterministic calculation records, not re-computed in the browser.

## 6. Security and Credential Management

Secrets:

- Store Firebase Admin, model/search provider, database, Redis, object-storage, and Sentry auth credentials only in server-side secret managers.
- Never commit real `.env` files.
- Never put DeepSeek credentials in Next.js public env vars.
- Never put `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`, `SENTRY_AUTH_TOKEN`, or backend service credentials in `NEXT_PUBLIC_*` variables.
- Firebase Web configuration may use `NEXT_PUBLIC_*`; treat it as public metadata and enforce security through Firebase Authentication, FastAPI verification, and PostgreSQL authorization.

Uploads:

- Limit file type and size.
- Never execute uploaded files.
- Store outside executable paths.
- Parse in isolated worker code.

URL fetching:

- Block unsafe schemes.
- Block localhost, private IPs, reserved IPs, link-local addresses, and cloud metadata endpoints.
- Revalidate redirects.
- Re-check DNS at connection time.
- Enforce timeouts and response-size limits.

Authorization:

- Verify ownership or share policy for every run, source, snapshot, export, saved report, and feedback route.

Logging:

- Avoid access tokens, passwords, full private uploads, and unnecessary personal content.
- Log stable ids, status codes, timings, and error categories.

Prompt injection:

- Treat retrieved pages as untrusted data.
- Never allow source text to alter system instructions or workflow policy.

## 7. Evaluation and Observability

Operational metrics:

- search-to-fetch conversion,
- extraction success rate,
- median fetch latency,
- Playwright fallback rate,
- cache hit rate,
- duplicate-cluster rate,
- evidence yield,
- cost per verification,
- DeepSeek token usage,
- source accessibility failure rate,
- citation-audit failure rate,
- queue length,
- run duration,
- retry count,
- cancellation rate.

Quality evaluations:

- verdict accuracy,
- macro-F1 across supported/refuted/mixed/insufficient classes,
- attribution accuracy,
- evidence precision and recall,
- passage recall against human-required evidence,
- citation entailment,
- URL relevance precision,
- primary-source recall,
- extraction fidelity for numbers, dates, units, speakers, quotations,
- numerical accuracy,
- source-clustering accuracy,
- confidence calibration error,
- unsupported-statement rate.

Security regression tests:

- SSRF,
- redirect abuse,
- oversized files,
- hostile HTML,
- unsupported executable files,
- prompt injection,
- cross-user access attempts.

## 8. CI/CD and Deployment

GitHub Actions pipeline:

1. Install dependencies.
2. Run TypeScript checks.
3. Run frontend tests.
4. Run Python linting.
5. Run Python type checks.
6. Run API and worker tests.
7. Build Next.js.
8. Build API and worker containers.
9. Run Alembic migration checks.
10. Run evaluation smoke tests.
11. Run security regression tests.
12. Allow Vercel to create preview deployments from GitHub pull requests.
13. Run one hosted-demo smoke test against the configured HTTPS API and Vercel URL.
14. Run Alembic before starting an incompatible application revision.
15. Deploy the chosen demo revision. A separate staging promotion path is optional.

Deployment topology:

- Next.js frontend on Vercel, connected directly to the GitHub repository with `apps/web` as the project root once the monorepo is created.
- Firebase Authentication supplies user identity only; Firebase Hosting is not used.
- FastAPI, Celery, PostgreSQL/pgvector, and Redis run as containers on one AWS EC2 demo host.
- Private S3-compatible storage remains server-side and non-public.
- Sentry for application monitoring.
- LangSmith-compatible tracing or custom trace store for worker evaluations.

Deployment environment ownership:

- Configure public Next.js variables for the stable Vercel demo deployment. Vercel's `Production` environment name is a platform label, not a production-SaaS claim.
- Configure Firebase Admin, DeepSeek, search, database, Redis, object-storage, and backend Sentry values only on the FastAPI/worker host.
- Configure `WEB_APP_URL` and `CORS_ALLOWED_ORIGINS` on FastAPI with the exact Vercel/custom-domain origins.
- GitHub-connected Vercel deployment does not require `VERCEL_TOKEN`, `VERCEL_ORG_ID`, or `VERCEL_PROJECT_ID`.
- A host that builds directly from GitHub does not require application-level container-registry credentials.

Migration rule:

- Run database migrations as a controlled deployment step before incompatible code is activated.

## 9. Hosted Demo Milestone

Deliver a responsive web app that:

1. Accepts a text claim or article URL.
2. Authenticates the user.
3. Creates a durable verification run.
4. Queues a Celery job.
5. Streams observable progress over SSE.
6. Runs a LangGraph workflow with DeepSeek structured outputs.
7. Performs targeted retrieval with secure httpx fetching and Trafilatura extraction.
8. Stores sources, snapshots, passages, evidence, calculations, and events.
9. Applies deterministic scoring and citation auditing.
10. Displays a citation-grounded report with exact passages, limitations, versions, and the evidence-reviewed timestamp.

For the current side-project scope, one approved claim path is enough for the hosted demo. Advanced provenance views, additional input types, sharing, corrections, OCR, domain connectors, multilingual retrieval, and snapshot comparisons are optional follow-up work.

## 10. Implementation Order

1. Create the monorepo structure.
2. Build the Next.js application shell, routes, design system, and mocked report interface.
3. Build Firebase Web sign-in, FastAPI Firebase Admin token/session verification, Pydantic verification schemas, and PostgreSQL user/run persistence.
4. Add Alembic migrations for users, runs, claims, sources, snapshots, passages, evidence, calculations, events, versions, and pgvector.
5. Add Redis, Celery, run queues, cancellation flags, and Redis Stream progress.
6. Add SSE endpoint and frontend live research view.
7. Implement DeepSeek client wrapper and structured Pydantic agent outputs.
8. Implement LangGraph nodes for intake, decomposition, planner, evidence classification, synthesis, and citation audit.
9. Implement targeted retrieval: search, URL guard, cache, httpx fetcher, Trafilatura extraction, Beautiful Soup fallback, PyMuPDF PDF parsing.
10. Add passage segmentation, hashing, embedding generation through approved DeepSeek-compatible route, and pgvector search.
11. Add source provenance, dependency clustering, and source graph API.
12. Add deterministic evidence quality, support, confidence, independence, quote fidelity, context, and label services.
13. Add numerical auditing with Decimal.
14. Add report workspace, source drawer, React Flow graph, and Recharts score visualizations.
15. Add feedback, corrections, exports, saved reports, and history.
16. Add Sentry, worker metrics, provider usage metrics, and evaluation harness.
17. Add focused security regressions for the hosted-demo boundary.
18. Close the full workflow through synthesis, citation audit, revision, and durable completion.
19. Restore and enforce every local and CI quality gate.
20. Add a deterministic full-stack end-to-end verification test.
21. Finish retrieval hardening, including the isolated Playwright fallback.
22. Build a human-reviewed evaluation corpus and calibrate the methodology.
23. Complete product, report, accessibility, and responsive acceptance testing.
24. Complete the security, privacy, retention, correction, and governance review.
25. Validate the hosted demo: HTTPS, Firebase sign-in, queue processing, and one durable citation-audited report.
26. Run broader release audits only if the user later expands the project beyond a side-project demo.

## 11. Non-Negotiable Product Language

Every completed report must communicate:

- what evidence was reviewed,
- when it was reviewed,
- which sources were inaccessible,
- how evidence supports or contradicts the exact claim,
- how attribution differs from factual content,
- how scores were calculated,
- what limitations remain.

Required timestamp:

```text
Evidence reviewed as of [date and time]. New evidence or corrections may change this assessment.
```

Elara.ai must answer only what the evidence supports. It must show what was found, how it was found, why each source was selected, which sources depend on one another, which evidence was inaccessible, and how the published methodology produced the final label.

## 12. Hosted-Demo Completion Plan

Steps 1-17 establish the planned product surface and its major subsystems. The current goal is not public-production readiness. Completion means the owner can run one credible hosted demonstration using the real API, worker, providers, and durable citation-audited report path.

### 12.1 Completion Bars

Use two explicit bars:

1. **Feature complete:** the relevant behavior exists and its focused tests pass.
2. **Hosted demo operational:** the Vercel frontend and AWS API are reachable over HTTPS; Firebase sign-in works; one approved claim is processed by Celery; the report and citation-audit records are durable; refresh/reconnect reloads PostgreSQL truth; and internal services and credentials remain non-public.

Public-production approval is out of scope. Do not add availability, certification, enterprise operations, or large-scale release gates unless the user explicitly changes the scope.

### 12.2 Step 18 - Full Workflow Closure

The real Celery path used by the hosted demo must execute the complete controlled workflow:

```text
QUEUED
-> VALIDATING
-> DECOMPOSING
-> RESEARCHING
-> EXTRACTING
-> ANALYZING_PROVENANCE
-> SCORING
-> SYNTHESIZING
-> AUDITING
-> COMPLETED
```

Required work:

- Remove runtime shortcuts that stop execution after numerical audit.
- Give the runtime entry point a name that reflects full verification rather than planning-only execution.
- Run synthesis and citation audit after deterministic scoring and numerical audit.
- Add a bounded citation-revision loop. Unsupported or partially supported sentences must be removed or revised from approved evidence and audited again.
- Fail with a concise public error when the configured revision limit is exhausted; never publish an unsupported report.
- Transition to `COMPLETED` only when the typed state passes the deterministic completion gate, the report and citation rows are durable, no recoverable errors remain, and cancellation has not won the race.
- Emit and mirror a durable `run.completed` event so SSE terminates and the frontend reloads authoritative PostgreSQL state.
- Make redelivery idempotent: do not duplicate claims, sources, passages, evidence, calculations, citations, or events, and do not rewind a terminal run.

Exit criteria:

- A real-runtime regression test proves the full status sequence reaches `COMPLETED`.
- Citation failure, cancellation, provider exhaustion, and redelivery tests prove invalid runs cannot reach `COMPLETED`.
- A completed run can be read through the report API and can create an authorized export.

### 12.3 Step 19 - Quality-Gate Closure

Fix every lint, type, test, migration, build, and container failure. Run the same commands and working directories used by GitHub Actions.

Required gates:

- Ruff over API, worker, and evaluations.
- Focused mypy checks plus any newly changed typed modules.
- Complete API, worker, evaluation, and frontend test suites.
- Frontend lint, TypeScript check, and optimized Next.js build.
- Alembic single-head check, upgrade SQL generation, and downgrade SQL review.
- API and worker container builds from a clean checkout.
- Security and evaluation gate jobs.

No known failure may be reclassified as harmless without a written reason. Tests must exercise the real hosted-demo runtime boundary, not only isolated graph assembly.

### 12.4 Step 20 - Deterministic Full-Stack Acceptance Test

Build a provider-independent integration environment using PostgreSQL/pgvector, Redis, S3-compatible storage, FastAPI, Celery, and deterministic DeepSeek and Brave test doubles.

The acceptance test must:

1. Authenticate a user through the API boundary.
2. Submit a verification and receive a durable queued run.
3. Dispatch the correct Celery queue.
4. Observe credentialed SSE progress without URL tokens.
5. Discover, retrieve, extract, snapshot, and segment controlled sources.
6. Persist provenance, evidence, calculations, model/prompt metadata, and citation rows.
7. Reach `COMPLETED` only after citation audit.
8. Load the report, sources, source graph, and calculations after a simulated browser refresh.
9. Create and download an authorized private export.
10. Prove a second user cannot access the run or any related artifact.

This test must run in CI without real provider credentials. One hosted-demo smoke may exercise real providers.

### 12.5 Step 21 - Retrieval Hardening

Replace the explicit Playwright placeholder with an isolated browser fallback while preserving static extraction as the default.

Playwright requirements:

- Run only after static extraction fails and the source is important enough.
- Apply the same scheme, hostname, DNS, IP, port, and redirect policy to every navigation and subrequest.
- Use a fresh context without user cookies or provider credentials.
- Block downloads, popups, unnecessary media, and nonessential third-party requests.
- Enforce navigation, total-time, response-size, DOM-size, and retry limits.
- Record fallback reason, parser version, extraction certainty, and inaccessible status.

Also test malformed and hostile HTML, JavaScript-only pages, oversized documents, page-aware PDF citations, paywalls, correction notices, changed snapshots, cache reuse, and distributed fetch locks.

Brave remains the selected search provider. Preserve partial results and use bounded retries on transient failure. Do not add a second provider without an explicit architecture decision.

### 12.6 Step 22 - Evaluation and Methodology Calibration

The two-case smoke fixture validates the harness, not the product. Build an approved, human-reviewed benchmark spanning finance, science, technology, current events, quotations, paraphrases, allegations, numerical claims, misleading context, and insufficient evidence.

Each benchmark case should define:

- atomic claims and importance;
- required primary sources and acceptable alternatives;
- supporting and contradicting passages;
- attribution and quote-fidelity expectations where applicable;
- expected labels and calculations;
- citation-entailment judgments;
- source-dependency clusters;
- inaccessible-source and ambiguity expectations.

Maintain separate development/calibration, locked validation, adversarial-security, and regression sets. Measure verdict macro-F1, attribution accuracy, evidence precision/recall, passage recall, primary-source recall, citation entailment, numerical accuracy, unsupported-statement rate, source clustering, confidence calibration/Brier score, latency, and cost.

Every formula, weight, threshold, or penalty change creates a new methodology version. A broad human-reviewed release benchmark is optional for the side-project demo unless the owner intends to present methodology-performance claims. Unsupported factual statements must still be rejected by citation audit.

### 12.7 Step 23 - Product and Report Acceptance

Verify the desktop demo path plus the loading, failure, reconnect, retry, and cancellation behavior the demo will exercise. Remove remaining demo-facing mock surfaces.

Every applicable completed report must expose:

- verdict and distinct score roles;
- evidence-reviewed timestamp and limitations;
- inaccessible sources and strongest credible contradiction;
- supporting and contradicting exact passages;
- page, section, or transcript positions;
- attribution separated from factual content;
- reproducible calculations and audit status;
- source dependencies;
- methodology, workflow, prompt, model, parser, retrieval, and source versions;
- feedback, correction, and authorized export controls.

TanStack Query remains the owner of server state. Browser charts consume server calculation records and never recompute authoritative scores.

### 12.8 Step 24 - Security, Privacy, and Governance Review

Keep focused checks for SSRF and redirects, prompt injection boundaries, cross-user access, signed URL expiry, cookies, exact-origin CORS, log/trace redaction, secret scanning, and private bucket policy. These protect credentials, private data, and report correctness even for a low-traffic demo. Enterprise-scale resource-exhaustion analysis and release certification are out of scope.

Document and implement policies for upload retention, snapshot retention, deletion, sharing, corrections, appeals, and high-impact allegations. Prevent automatic publication when stronger review controls are required. Store only the evidence needed for auditability and never silently delete a snapshot referenced by a completed report.

### 12.9 Step 25 - Hosted Demo Validation

Run the complete stack on the existing single AWS EC2 demo host. The web application and HTTPS API are browser reachable, while PostgreSQL, Redis, object storage, and the worker remain non-public. Keep Firebase Authentication, Brave Search, DeepSeek, Sentry auth, and tracing credentials server-side.

Required validation:

- the HTTPS API and Vercel web origin respond;
- API and worker run the same non-local compatible revision;
- Firebase sign-in and queue processing work;
- the private object store is non-public and stores object keys rather than permanent public URLs;
- one approved public or synthetic claim case reaches a durable, citation-audited report without placing private data in logs, traces, or test artifacts.

SSE reconnect, a signed export/ownership denial check, one backup, and a quick look at provider or worker errors are sensible if they are easy to run. Application rollback rehearsal, Redis restart drills, dead-job recovery, exhaustive provider checks, multi-AZ availability, production separation, formal alert routing, credential rotation, migration rollback rehearsal, and every-input live cases are optional and do not block the side-project demo.

### 12.10 Step 26 - Optional Demo Review

The hosted demo is operational when all of the following are true:

- The full workflow reaches `COMPLETED` through synthesis and citation audit.
- Citation failures cannot publish a report.
- The AWS environment passes the Step 25 smoke and one controlled claim with real services.
- Firebase authentication and the demo's private-data ownership boundary work.
- Known limitations are recorded without claiming production readiness.
- Documentation and the Graphify knowledge graph are current.

No formal versioned release audit is required for an owner-operated side project. Record only enough sanitized evidence to repeat the demo and diagnose failures. A future public-production audit begins only if the user explicitly changes the scope.
