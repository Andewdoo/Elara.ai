-- Elara Lite Mode Supabase schema and pgvector setup.
--
-- Scope:
-- - Additive public-demo storage only.
-- - Does not replace or modify the Full Mode FastAPI/PostgreSQL/Redis/Celery stack.
-- - Intended for Supabase Postgres, executed by an owner/admin in the SQL editor
--   or through a migration runner.
--
-- Server boundary:
-- - Browser clients may read only the optional public metadata view granted below.
-- - Lite retrieval and all writes must use server-side code with the Supabase
--   service-role key. Do not expose the service-role key to browser bundles.
-- - Retrieved evidence text is untrusted content. Application code must keep
--   retrieval bounds, thresholds, fallback decisions, scoring, and citation
--   presence checks deterministic.

begin;

create extension if not exists vector;
create extension if not exists pgcrypto;

do $$
begin
  create type public.lite_document_visibility as enum ('public', 'private', 'disabled');
exception
  when duplicate_object then null;
end $$;

do $$
begin
  create type public.lite_answer_status as enum (
    'answered',
    'insufficient_evidence',
    'unsupported_request',
    'audit_failed',
    'error'
  );
exception
  when duplicate_object then null;
end $$;

do $$
begin
  create type public.lite_support_status as enum (
    'support',
    'contradiction',
    'background',
    'irrelevant',
    'unsupported',
    'uncertain'
  );
exception
  when duplicate_object then null;
end $$;

do $$
begin
  create type public.lite_citation_audit_status as enum (
    'pending',
    'passed',
    'failed',
    'revised',
    'not_applicable'
  );
exception
  when duplicate_object then null;
end $$;

create or replace function public.lite_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.lite_documents (
  id uuid primary key default gen_random_uuid(),
  corpus_version text not null,
  title text not null,
  source_url text,
  publisher text,
  document_date date,
  ingested_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  visibility public.lite_document_visibility not null default 'private',
  source_content_hash text,
  metadata jsonb not null default '{}'::jsonb,
  constraint lite_documents_source_url_http
    check (source_url is null or source_url ~* '^https?://'),
  constraint lite_documents_corpus_source_hash_unique unique (corpus_version, source_content_hash)
);

create table if not exists public.lite_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.lite_documents(id) on delete cascade,
  corpus_version text not null,
  chunk_index integer not null,
  chunk_text text not null,
  -- Keep this dimension aligned with the approved server-side Lite embedding route.
  -- If a future DeepSeek-compatible embedding route requires a different dimension,
  -- create a new migration rather than mutating stored vectors in place.
  embedding vector(1536),
  heading_path text[] not null default '{}'::text[],
  page_number integer,
  section_label text,
  paragraph_index integer,
  char_start integer,
  char_end integer,
  content_hash text not null,
  source_citation_label text not null,
  metadata jsonb not null default '{}'::jsonb,
  search_vector tsvector generated always as (
    to_tsvector('english', coalesce(chunk_text, ''))
  ) stored,
  created_at timestamptz not null default now(),
  constraint lite_chunks_chunk_index_nonnegative check (chunk_index >= 0),
  constraint lite_chunks_page_positive check (page_number is null or page_number > 0),
  constraint lite_chunks_paragraph_nonnegative check (paragraph_index is null or paragraph_index >= 0),
  constraint lite_chunks_offsets_valid check (
    (char_start is null and char_end is null)
    or (char_start is not null and char_end is not null and char_start >= 0 and char_end >= char_start)
  ),
  constraint lite_chunks_document_chunk_unique unique (document_id, chunk_index),
  constraint lite_chunks_corpus_hash_unique unique (corpus_version, content_hash)
);

create table if not exists public.lite_runs (
  id uuid primary key default gen_random_uuid(),
  submitted_text text not null,
  input_kind text,
  corpus_version text not null,
  answer_status public.lite_answer_status not null,
  generated_answer text,
  generated_answer_metadata jsonb not null default '{}'::jsonb,
  model_provider text not null default 'deepseek',
  model_name text,
  prompt_versions jsonb not null default '{}'::jsonb,
  workflow_version text,
  retrieval_metadata jsonb not null default '{}'::jsonb,
  citation_audit_status public.lite_citation_audit_status not null default 'pending',
  non_sensitive_telemetry jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint lite_runs_submitted_text_nonempty check (length(btrim(submitted_text)) > 0),
  constraint lite_runs_model_provider_deepseek check (model_provider = 'deepseek'),
  constraint lite_runs_completed_after_created check (completed_at is null or completed_at >= created_at)
);

create table if not exists public.lite_run_citations (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.lite_runs(id) on delete cascade,
  chunk_id uuid not null references public.lite_chunks(id) on delete restrict,
  answer_sentence_index integer not null,
  chunk_sentence_indexes integer[] not null default '{}'::integer[],
  support_status public.lite_support_status not null,
  audit_status public.lite_citation_audit_status not null,
  cited_text text,
  chunk_content_hash_snapshot text not null,
  source_citation_label_snapshot text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint lite_run_citations_sentence_nonnegative check (answer_sentence_index >= 0)
);

create table if not exists public.lite_feedback (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.lite_runs(id) on delete set null,
  rating smallint,
  category text,
  feedback_text text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint lite_feedback_rating_range check (rating is null or rating between 1 and 5)
);

create table if not exists public.lite_eval_cases (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  corpus_version text not null,
  prompt text not null,
  expected_status public.lite_answer_status,
  expected_citation_labels text[] not null default '{}'::text[],
  metadata jsonb not null default '{}'::jsonb,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists lite_documents_set_updated_at on public.lite_documents;
create trigger lite_documents_set_updated_at
before update on public.lite_documents
for each row execute function public.lite_set_updated_at();

drop trigger if exists lite_eval_cases_set_updated_at on public.lite_eval_cases;
create trigger lite_eval_cases_set_updated_at
before update on public.lite_eval_cases
for each row execute function public.lite_set_updated_at();

create index if not exists idx_lite_documents_corpus_version
  on public.lite_documents (corpus_version);

create index if not exists idx_lite_documents_visibility
  on public.lite_documents (visibility);

create index if not exists idx_lite_documents_document_date
  on public.lite_documents (document_date desc nulls last);

create index if not exists idx_lite_documents_content_hash
  on public.lite_documents (source_content_hash);

create index if not exists idx_lite_chunks_document_id
  on public.lite_chunks (document_id);

create index if not exists idx_lite_chunks_corpus_version
  on public.lite_chunks (corpus_version);

create index if not exists idx_lite_chunks_content_hash
  on public.lite_chunks (content_hash);

create index if not exists idx_lite_chunks_search_vector
  on public.lite_chunks using gin (search_vector);

create index if not exists idx_lite_chunks_embedding_hnsw
  on public.lite_chunks using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create index if not exists idx_lite_runs_created_at
  on public.lite_runs (created_at desc);

create index if not exists idx_lite_runs_corpus_version
  on public.lite_runs (corpus_version);

create index if not exists idx_lite_run_citations_run_id
  on public.lite_run_citations (run_id);

create index if not exists idx_lite_run_citations_chunk_id
  on public.lite_run_citations (chunk_id);

create index if not exists idx_lite_feedback_run_id
  on public.lite_feedback (run_id);

create index if not exists idx_lite_eval_cases_corpus_enabled
  on public.lite_eval_cases (corpus_version, enabled);

alter table public.lite_documents enable row level security;
alter table public.lite_chunks enable row level security;
alter table public.lite_runs enable row level security;
alter table public.lite_run_citations enable row level security;
alter table public.lite_feedback enable row level security;
alter table public.lite_eval_cases enable row level security;

drop policy if exists lite_documents_public_metadata_read on public.lite_documents;
create policy lite_documents_public_metadata_read
on public.lite_documents
for select
to anon, authenticated
using (visibility = 'public');

drop policy if exists lite_documents_no_public_insert on public.lite_documents;
create policy lite_documents_no_public_insert
on public.lite_documents
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_documents_no_public_update on public.lite_documents;
create policy lite_documents_no_public_update
on public.lite_documents
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_documents_no_public_delete on public.lite_documents;
create policy lite_documents_no_public_delete
on public.lite_documents
for delete
to anon, authenticated
using (false);

drop policy if exists lite_chunks_no_public_select on public.lite_chunks;
create policy lite_chunks_no_public_select
on public.lite_chunks
for select
to anon, authenticated
using (false);

drop policy if exists lite_chunks_no_public_insert on public.lite_chunks;
create policy lite_chunks_no_public_insert
on public.lite_chunks
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_chunks_no_public_update on public.lite_chunks;
create policy lite_chunks_no_public_update
on public.lite_chunks
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_chunks_no_public_delete on public.lite_chunks;
create policy lite_chunks_no_public_delete
on public.lite_chunks
for delete
to anon, authenticated
using (false);

drop policy if exists lite_runs_no_public_select on public.lite_runs;
create policy lite_runs_no_public_select
on public.lite_runs
for select
to anon, authenticated
using (false);

drop policy if exists lite_runs_no_public_insert on public.lite_runs;
create policy lite_runs_no_public_insert
on public.lite_runs
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_runs_no_public_update on public.lite_runs;
create policy lite_runs_no_public_update
on public.lite_runs
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_runs_no_public_delete on public.lite_runs;
create policy lite_runs_no_public_delete
on public.lite_runs
for delete
to anon, authenticated
using (false);

drop policy if exists lite_run_citations_no_public_select on public.lite_run_citations;
create policy lite_run_citations_no_public_select
on public.lite_run_citations
for select
to anon, authenticated
using (false);

drop policy if exists lite_run_citations_no_public_insert on public.lite_run_citations;
create policy lite_run_citations_no_public_insert
on public.lite_run_citations
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_run_citations_no_public_update on public.lite_run_citations;
create policy lite_run_citations_no_public_update
on public.lite_run_citations
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_run_citations_no_public_delete on public.lite_run_citations;
create policy lite_run_citations_no_public_delete
on public.lite_run_citations
for delete
to anon, authenticated
using (false);

drop policy if exists lite_feedback_no_public_select on public.lite_feedback;
create policy lite_feedback_no_public_select
on public.lite_feedback
for select
to anon, authenticated
using (false);

drop policy if exists lite_feedback_no_public_insert on public.lite_feedback;
create policy lite_feedback_no_public_insert
on public.lite_feedback
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_feedback_no_public_update on public.lite_feedback;
create policy lite_feedback_no_public_update
on public.lite_feedback
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_feedback_no_public_delete on public.lite_feedback;
create policy lite_feedback_no_public_delete
on public.lite_feedback
for delete
to anon, authenticated
using (false);

drop policy if exists lite_eval_cases_no_public_select on public.lite_eval_cases;
create policy lite_eval_cases_no_public_select
on public.lite_eval_cases
for select
to anon, authenticated
using (false);

drop policy if exists lite_eval_cases_no_public_insert on public.lite_eval_cases;
create policy lite_eval_cases_no_public_insert
on public.lite_eval_cases
for insert
to anon, authenticated
with check (false);

drop policy if exists lite_eval_cases_no_public_update on public.lite_eval_cases;
create policy lite_eval_cases_no_public_update
on public.lite_eval_cases
for update
to anon, authenticated
using (false)
with check (false);

drop policy if exists lite_eval_cases_no_public_delete on public.lite_eval_cases;
create policy lite_eval_cases_no_public_delete
on public.lite_eval_cases
for delete
to anon, authenticated
using (false);

create or replace view public.lite_public_documents
with (security_invoker = true)
as
select
  id,
  corpus_version,
  title,
  source_url,
  publisher,
  document_date,
  ingested_at,
  source_content_hash,
  metadata
from public.lite_documents
where visibility = 'public';

create or replace function public.match_lite_chunks(
  query_embedding vector(1536),
  match_count integer default 8,
  min_similarity double precision default 0.0,
  filter_corpus_version text default null,
  filter_document_ids uuid[] default null,
  filter_publisher text default null,
  filter_document_date_start date default null,
  filter_document_date_end date default null,
  include_private boolean default false
)
returns table (
  chunk_id uuid,
  document_id uuid,
  title text,
  source_url text,
  publisher text,
  document_date date,
  corpus_version text,
  chunk_text text,
  heading_path text[],
  page_number integer,
  section_label text,
  paragraph_index integer,
  content_hash text,
  source_citation_label text,
  similarity double precision
)
language sql
stable
security invoker
set search_path = public
as $$
  with bounds as (
    select
      least(greatest(coalesce(match_count, 8), 1), 50) as bounded_count,
      least(greatest(coalesce(min_similarity, 0.0), 0.0), 1.0) as bounded_similarity
  )
  select
    c.id as chunk_id,
    c.document_id,
    d.title,
    d.source_url,
    d.publisher,
    d.document_date,
    c.corpus_version,
    c.chunk_text,
    c.heading_path,
    c.page_number,
    c.section_label,
    c.paragraph_index,
    c.content_hash,
    c.source_citation_label,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.lite_chunks c
  join public.lite_documents d on d.id = c.document_id
  cross join bounds b
  where c.embedding is not null
    and (include_private or d.visibility = 'public')
    and (filter_corpus_version is null or c.corpus_version = filter_corpus_version)
    and (filter_document_ids is null or c.document_id = any(filter_document_ids))
    and (filter_publisher is null or d.publisher = filter_publisher)
    and (filter_document_date_start is null or d.document_date >= filter_document_date_start)
    and (filter_document_date_end is null or d.document_date <= filter_document_date_end)
    and (1 - (c.embedding <=> query_embedding)) >= b.bounded_similarity
  order by c.embedding <=> query_embedding, d.document_date desc nulls last, c.chunk_index
  limit (select bounded_count from bounds);
$$;

comment on table public.lite_documents is
  'Curated Lite Mode public-demo source metadata. Does not replace Full Mode PostgreSQL source records.';

comment on table public.lite_chunks is
  'Curated Lite Mode evidence chunks with pgvector embeddings and exact citation metadata.';

comment on table public.lite_runs is
  'Lite Mode demo run records generated by server-side routes only.';

comment on table public.lite_run_citations is
  'Sentence-level Lite citation audit records linking generated answer sentences to stored chunks.';

comment on function public.match_lite_chunks(vector, integer, double precision, text, uuid[], text, date, date, boolean) is
  'Server-side Lite vector retrieval over curated chunks with deterministic bounds and metadata filters.';

revoke all on table public.lite_documents from anon, authenticated;
revoke all on table public.lite_chunks from anon, authenticated;
revoke all on table public.lite_runs from anon, authenticated;
revoke all on table public.lite_run_citations from anon, authenticated;
revoke all on table public.lite_feedback from anon, authenticated;
revoke all on table public.lite_eval_cases from anon, authenticated;
revoke all on table public.lite_public_documents from anon, authenticated;
revoke execute on function public.match_lite_chunks(
  vector,
  integer,
  double precision,
  text,
  uuid[],
  text,
  date,
  date,
  boolean
) from public, anon, authenticated;

grant select on table public.lite_public_documents to anon, authenticated;
grant select on table public.lite_documents to anon, authenticated;
grant all on table public.lite_documents to service_role;
grant all on table public.lite_chunks to service_role;
grant all on table public.lite_runs to service_role;
grant all on table public.lite_run_citations to service_role;
grant all on table public.lite_feedback to service_role;
grant all on table public.lite_eval_cases to service_role;
grant execute on function public.match_lite_chunks(
  vector,
  integer,
  double precision,
  text,
  uuid[],
  text,
  date,
  date,
  boolean
) to service_role;

commit;

-- Optional lexical or hybrid retrieval can be layered in server-side code by
-- querying lite_chunks.search_vector with metadata filters and merging those
-- deterministic candidates with match_lite_chunks results. Keep final candidate
-- limits, thresholds, and insufficient-evidence fallbacks in application code.
--
-- If the Supabase pgvector version does not support HNSW, replace
-- idx_lite_chunks_embedding_hnsw with an ivfflat cosine index after loading a
-- representative corpus:
--
--   create index idx_lite_chunks_embedding_ivfflat
--     on public.lite_chunks using ivfflat (embedding vector_cosine_ops)
--     with (lists = 100)
--     where embedding is not null;
--
-- Deferred by design:
-- Do not create or populate lite_cached_responses in Lite v1. That table belongs
-- to a later phase after Full Mode is completed, temporarily hosted, exercised
-- with controlled cases, and 10-20 reviewed completed reports are captured for
-- public demo use.
