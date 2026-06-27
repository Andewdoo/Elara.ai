"""Create durable verification, evidence, provenance, and version schema.

Revision ID: 20260626_0001
Revises: None
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "20260626_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_dimension() -> int:
    try:
        dimension = int(os.getenv("PASSAGE_EMBEDDING_DIMENSION", "1536"))
    except ValueError as exc:
        raise RuntimeError("PASSAGE_EMBEDDING_DIMENSION must be an integer") from exc
    if dimension <= 0:
        raise RuntimeError("PASSAGE_EMBEDDING_DIMENSION must be positive")
    return dimension


ENUMS = {
    "run_status": (
        "QUEUED", "VALIDATING", "DECOMPOSING", "RESEARCHING", "EXTRACTING",
        "ANALYZING_PROVENANCE", "SCORING", "SYNTHESIZING", "AUDITING",
        "COMPLETED", "FAILED", "CANCELLED",
    ),
    "input_type": (
        "CLAIM", "ARTICLE_URL", "ARTICLE_TEXT", "QUOTE", "PARAPHRASE", "UPLOADED_DOCUMENT",
    ),
    "research_depth": ("QUICK", "STANDARD", "DEEP"),
    "source_type": (
        "PRIMARY", "OFFICIAL_SELF_REPORT", "INDEPENDENT_ANALYSIS", "SECONDARY_REPORT",
        "DERIVATIVE_REPORT", "OPINION", "UNKNOWN",
    ),
    "access_status": (
        "PENDING", "FETCHED", "INACCESSIBLE", "PAYWALLED", "BOT_BLOCKED", "UNSUPPORTED", "FAILED",
    ),
    "evidence_stance": (
        "STRONGLY_CONTRADICTS", "PARTIALLY_CONTRADICTS", "NEUTRAL",
        "PARTIALLY_SUPPORTS", "STRONGLY_SUPPORTS",
    ),
    "dependency_relationship": (
        "CITES", "REPUBLISHES", "QUOTES", "DERIVES_FROM", "USES_SAME_DATA", "POSSIBLE_DUPLICATE",
    ),
}


TABLE_SQL = (
    """CREATE TABLE methodology_versions (
        id uuid PRIMARY KEY, version varchar(100) NOT NULL UNIQUE,
        scoring_config jsonb NOT NULL, retrieval_config jsonb NOT NULL,
        released_at timestamptz NOT NULL, active boolean NOT NULL DEFAULT false
    )""",
    """CREATE TABLE users (
        id uuid PRIMARY KEY, auth_provider varchar(50) NOT NULL, auth_subject varchar(255) NOT NULL,
        email citext NOT NULL UNIQUE, display_name varchar(255), plan_tier varchar(50) NOT NULL,
        role varchar(50) NOT NULL DEFAULT 'user', usage_limits jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, deleted_at timestamptz,
        CONSTRAINT uq_users_auth_identity UNIQUE (auth_provider, auth_subject)
    )""",
    """CREATE TABLE verification_runs (
        id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
        input_type input_type NOT NULL, research_depth research_depth NOT NULL, status run_status NOT NULL,
        submitted_text text, submitted_url text, upload_object_path text,
        normalized_target jsonb NOT NULL DEFAULT '{}'::jsonb, title text, verdict varchar(100),
        evidence_support integer, verdict_confidence integer, source_independence integer,
        context_completeness integer,
        methodology_version_id uuid REFERENCES methodology_versions(id) ON DELETE RESTRICT,
        workflow_version varchar(100) NOT NULL, model_versions jsonb NOT NULL DEFAULT '{}'::jsonb,
        prompt_versions jsonb NOT NULL DEFAULT '{}'::jsonb, parser_versions jsonb NOT NULL DEFAULT '{}'::jsonb,
        queued_at timestamptz NOT NULL, started_at timestamptz, completed_at timestamptz, failed_at timestamptz,
        failure_code varchar(100), failure_message text, cancellation_requested_at timestamptz,
        evidence_reviewed_at timestamptz, visibility varchar(30) NOT NULL DEFAULT 'private',
        share_token_hash varchar(128), created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
        CONSTRAINT ck_verification_runs_evidence_support CHECK (evidence_support IS NULL OR evidence_support BETWEEN 0 AND 100),
        CONSTRAINT ck_verification_runs_verdict_confidence CHECK (verdict_confidence IS NULL OR verdict_confidence BETWEEN 0 AND 100),
        CONSTRAINT ck_verification_runs_source_independence CHECK (source_independence IS NULL OR source_independence BETWEEN 0 AND 100),
        CONSTRAINT ck_verification_runs_context_completeness CHECK (context_completeness IS NULL OR context_completeness BETWEEN 0 AND 100)
    )""",
    """CREATE TABLE atomic_claims (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        parent_claim_id uuid REFERENCES atomic_claims(id) ON DELETE SET NULL,
        claim_text text NOT NULL, normalized_claim text, claim_type varchar(100) NOT NULL,
        importance_weight integer NOT NULL, entities jsonb NOT NULL DEFAULT '[]'::jsonb, time_period text,
        locations jsonb NOT NULL DEFAULT '[]'::jsonb, metrics jsonb NOT NULL DEFAULT '[]'::jsonb,
        comparison text, ambiguities jsonb NOT NULL DEFAULT '[]'::jsonb,
        fact_checkable boolean NOT NULL DEFAULT true, support_score integer, confidence_score integer,
        context_completeness integer, final_label varchar(100), gates jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL,
        CONSTRAINT ck_atomic_claim_importance CHECK (importance_weight BETWEEN 1 AND 3),
        CONSTRAINT ck_atomic_claim_support_score CHECK (support_score IS NULL OR support_score BETWEEN 0 AND 100),
        CONSTRAINT ck_atomic_claim_confidence_score CHECK (confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100),
        CONSTRAINT ck_atomic_claim_context_completeness CHECK (context_completeness IS NULL OR context_completeness BETWEEN 0 AND 100)
    )""",
    """CREATE TABLE search_queries (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        atomic_claim_id uuid REFERENCES atomic_claims(id) ON DELETE CASCADE,
        family varchar(100) NOT NULL, query_text text NOT NULL, generated_by_node varchar(100) NOT NULL,
        priority numeric(6,4), executed_at timestamptz, result_count integer, created_at timestamptz NOT NULL,
        CONSTRAINT ck_search_queries_priority CHECK (priority IS NULL OR priority BETWEEN 0 AND 1)
    )""",
    """CREATE TABLE sources (
        id uuid PRIMARY KEY, canonical_url text NOT NULL UNIQUE, domain varchar(255) NOT NULL,
        title text, author text, publisher text, source_type source_type NOT NULL DEFAULT 'UNKNOWN',
        content_type varchar(255), robots_or_policy_status varchar(100),
        first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL
    )""",
    """CREATE TABLE source_snapshots (
        id uuid PRIMARY KEY, source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        version_number integer NOT NULL, retrieved_at timestamptz NOT NULL, published_at timestamptz,
        updated_at timestamptz, access_status access_status NOT NULL, content_hash varchar(128),
        snapshot_path text, parser_name varchar(100), parser_version varchar(100),
        extraction_quality numeric(6,4), correction_status varchar(100),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb, failure_reason text, created_at timestamptz NOT NULL,
        CONSTRAINT ck_source_snapshots_version_positive CHECK (version_number > 0),
        CONSTRAINT ck_source_snapshots_extraction_quality CHECK (extraction_quality IS NULL OR extraction_quality BETWEEN 0 AND 1),
        CONSTRAINT uq_source_snapshots_id_source UNIQUE (id, source_id),
        CONSTRAINT uq_source_snapshots_source_version UNIQUE (source_id, version_number)
    )""",
    """CREATE TABLE run_sources (
        run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        snapshot_id uuid,
        role varchar(100) NOT NULL, retrieval_reason text, priority_score numeric(6,4), selected_rank integer,
        inaccessible_reason text, created_at timestamptz NOT NULL,
        CONSTRAINT pk_run_sources PRIMARY KEY (run_id, source_id),
        CONSTRAINT fk_run_sources_snapshot_source FOREIGN KEY (snapshot_id, source_id)
            REFERENCES source_snapshots(id, source_id) ON DELETE RESTRICT,
        CONSTRAINT ck_run_sources_priority CHECK (priority_score IS NULL OR priority_score BETWEEN 0 AND 1)
    )""",
    """CREATE TABLE source_passages (
        id uuid PRIMARY KEY, snapshot_id uuid NOT NULL,
        source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE, text text NOT NULL,
        text_hash varchar(128) NOT NULL, heading_path text, page_or_position varchar(255),
        paragraph_index integer, speaker text, table_ref text,
        embedding vector(__EMBEDDING_DIMENSION__), embedding_model varchar(255),
        extraction_certainty numeric(6,4) NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL,
        CONSTRAINT fk_source_passages_snapshot_source FOREIGN KEY (snapshot_id, source_id)
            REFERENCES source_snapshots(id, source_id) ON DELETE CASCADE,
        CONSTRAINT ck_source_passages_extraction_certainty CHECK (extraction_certainty BETWEEN 0 AND 1),
        CONSTRAINT uq_source_passages_snapshot_text_hash UNIQUE (snapshot_id, text_hash)
    )""",
    """CREATE TABLE evidence_items (
        id uuid PRIMARY KEY, atomic_claim_id uuid NOT NULL REFERENCES atomic_claims(id) ON DELETE CASCADE,
        passage_id uuid NOT NULL REFERENCES source_passages(id) ON DELETE CASCADE,
        stance evidence_stance NOT NULL, stance_value numeric(4,2) NOT NULL,
        relevance numeric(6,4) NOT NULL, directness numeric(6,4) NOT NULL,
        authority numeric(6,4) NOT NULL, transparency numeric(6,4) NOT NULL,
        temporal_fit numeric(6,4) NOT NULL, extraction_certainty numeric(6,4) NOT NULL,
        base_quality numeric(8,6) NOT NULL, dependency_multiplier numeric(6,4) NOT NULL,
        adjusted_weight numeric(8,6) NOT NULL, rejection_reason text,
        citation_status varchar(50) NOT NULL DEFAULT 'pending', created_at timestamptz NOT NULL,
        CONSTRAINT ck_evidence_items_stance_value CHECK (stance_value BETWEEN -1 AND 1),
        CONSTRAINT ck_evidence_items_relevance CHECK (relevance BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_directness CHECK (directness BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_authority CHECK (authority BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_transparency CHECK (transparency BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_temporal_fit CHECK (temporal_fit BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_extraction_certainty CHECK (extraction_certainty BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_base_quality CHECK (base_quality BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_dependency_multiplier CHECK (dependency_multiplier BETWEEN 0 AND 1),
        CONSTRAINT ck_evidence_items_adjusted_weight CHECK (adjusted_weight BETWEEN 0 AND 1),
        CONSTRAINT uq_evidence_items_claim_passage UNIQUE (atomic_claim_id, passage_id)
    )""",
    """CREATE TABLE information_clusters (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        label text NOT NULL, origin_type varchar(100), representative_source_id uuid REFERENCES sources(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL
    )""",
    """CREATE TABLE source_dependencies (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        parent_source_id uuid NOT NULL REFERENCES sources(id), child_source_id uuid NOT NULL REFERENCES sources(id),
        relationship dependency_relationship NOT NULL, confidence numeric(6,4) NOT NULL,
        detection_method varchar(100) NOT NULL,
        information_cluster_id uuid REFERENCES information_clusters(id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL,
        CONSTRAINT ck_source_dependencies_not_self CHECK (parent_source_id <> child_source_id),
        CONSTRAINT ck_source_dependencies_confidence CHECK (confidence BETWEEN 0 AND 1),
        CONSTRAINT uq_source_dependencies_edge UNIQUE (run_id, parent_source_id, child_source_id, relationship)
    )""",
    """CREATE TABLE calculations (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        atomic_claim_id uuid REFERENCES atomic_claims(id) ON DELETE CASCADE,
        formula_name varchar(100) NOT NULL, formula_text text NOT NULL,
        inputs jsonb NOT NULL, result jsonb NOT NULL, units varchar(100),
        decimal_context jsonb NOT NULL, audit_status varchar(50) NOT NULL, created_at timestamptz NOT NULL
    )""",
    """CREATE TABLE agent_events (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        sequence integer NOT NULL, stage run_status NOT NULL, event_type varchar(100) NOT NULL,
        public_message text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL,
        CONSTRAINT uq_agent_events_run_sequence UNIQUE (run_id, sequence)
    )""",
    """CREATE TABLE report_citations (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        atomic_claim_id uuid REFERENCES atomic_claims(id), report_section varchar(100) NOT NULL,
        sentence_text text NOT NULL, passage_id uuid NOT NULL REFERENCES source_passages(id),
        audit_status varchar(50) NOT NULL, audit_note text, created_at timestamptz NOT NULL
    )""",
    """CREATE TABLE user_feedback (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users(id), category varchar(100) NOT NULL, message text NOT NULL,
        source_url text, status varchar(50) NOT NULL DEFAULT 'open',
        created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
    )""",
    """CREATE TABLE exports (
        id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
        export_type varchar(50) NOT NULL, object_path text NOT NULL, content_hash varchar(128) NOT NULL,
        created_at timestamptz NOT NULL
    )""",
)


POST_TABLE_SQL = (
    """CREATE FUNCTION protect_methodology_version_config() RETURNS trigger AS $$
    BEGIN
        IF NEW.id <> OLD.id
            OR NEW.version <> OLD.version
            OR NEW.scoring_config <> OLD.scoring_config
            OR NEW.retrieval_config <> OLD.retrieval_config
            OR NEW.released_at <> OLD.released_at THEN
            RAISE EXCEPTION 'methodology version configuration is immutable';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER trg_methodology_versions_immutable
    BEFORE UPDATE ON methodology_versions
    FOR EACH ROW EXECUTE FUNCTION protect_methodology_version_config()""",
    """CREATE FUNCTION reject_source_snapshot_update() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'source_snapshots are immutable; create a new version';
    END;
    $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER trg_source_snapshots_immutable
    BEFORE UPDATE ON source_snapshots
    FOR EACH ROW EXECUTE FUNCTION reject_source_snapshot_update()""",
)


INDEX_SQL = (
    "CREATE UNIQUE INDEX uq_methodology_versions_one_active ON methodology_versions (active) WHERE active",
    "CREATE INDEX ix_users_active ON users (id) WHERE deleted_at IS NULL",
    "CREATE INDEX ix_verification_runs_owner_created ON verification_runs (user_id, created_at DESC)",
    "CREATE INDEX ix_verification_runs_status_queued ON verification_runs (status, queued_at)",
    "CREATE INDEX ix_verification_runs_visibility ON verification_runs (visibility)",
    "CREATE INDEX ix_verification_runs_share_token ON verification_runs (share_token_hash) WHERE share_token_hash IS NOT NULL",
    "CREATE INDEX ix_atomic_claims_run_importance ON atomic_claims (run_id, importance_weight DESC)",
    "CREATE INDEX ix_atomic_claims_entities_gin ON atomic_claims USING gin (entities)",
    "CREATE INDEX ix_atomic_claims_metrics_gin ON atomic_claims USING gin (metrics)",
    "CREATE INDEX ix_search_queries_run_family ON search_queries (run_id, family)",
    "CREATE INDEX ix_search_queries_claim_family ON search_queries (atomic_claim_id, family)",
    "CREATE INDEX ix_sources_domain ON sources (domain)",
    "CREATE INDEX ix_sources_source_type ON sources (source_type)",
    "CREATE INDEX ix_source_snapshots_source_retrieved ON source_snapshots (source_id, retrieved_at DESC)",
    "CREATE INDEX ix_source_snapshots_content_hash ON source_snapshots (content_hash)",
    "CREATE INDEX ix_source_snapshots_access_status ON source_snapshots (access_status)",
    "CREATE INDEX ix_source_snapshots_source_content_hash ON source_snapshots (source_id, content_hash)",
    "CREATE INDEX ix_run_sources_snapshot ON run_sources (snapshot_id)",
    "CREATE INDEX ix_source_passages_source ON source_passages (source_id)",
    "CREATE INDEX ix_source_passages_snapshot ON source_passages (snapshot_id)",
    "CREATE INDEX ix_source_passages_text_hash ON source_passages (text_hash)",
    "CREATE INDEX ix_evidence_items_claim ON evidence_items (atomic_claim_id)",
    "CREATE INDEX ix_evidence_items_passage ON evidence_items (passage_id)",
    "CREATE INDEX ix_evidence_items_stance ON evidence_items (stance)",
    "CREATE INDEX ix_information_clusters_run ON information_clusters (run_id)",
    "CREATE INDEX ix_source_dependencies_run ON source_dependencies (run_id)",
    "CREATE INDEX ix_source_dependencies_parent ON source_dependencies (parent_source_id)",
    "CREATE INDEX ix_source_dependencies_child ON source_dependencies (child_source_id)",
    "CREATE INDEX ix_source_dependencies_run_relationship ON source_dependencies (run_id, relationship)",
    "CREATE INDEX ix_calculations_run_formula ON calculations (run_id, formula_name)",
    "CREATE INDEX ix_calculations_claim ON calculations (atomic_claim_id)",
    "CREATE INDEX ix_agent_events_run_created ON agent_events (run_id, created_at)",
    "CREATE INDEX ix_report_citations_run_section ON report_citations (run_id, report_section)",
    "CREATE INDEX ix_report_citations_passage ON report_citations (passage_id)",
    "CREATE INDEX ix_user_feedback_run_created ON user_feedback (run_id, created_at DESC)",
    "CREATE INDEX ix_user_feedback_user_created ON user_feedback (user_id, created_at)",
    "CREATE INDEX ix_user_feedback_status ON user_feedback (status)",
    "CREATE INDEX ix_exports_run_type_created ON exports (run_id, export_type, created_at DESC)",
)


DROP_TABLES = (
    "exports", "user_feedback", "report_citations", "agent_events", "calculations",
    "source_dependencies", "information_clusters", "evidence_items", "source_passages",
    "run_sources", "source_snapshots", "sources", "search_queries", "atomic_claims",
    "verification_runs", "users", "methodology_versions",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    for name, values in ENUMS.items():
        quoted_values = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({quoted_values})")
    dimension = str(_embedding_dimension())
    for statement in TABLE_SQL:
        op.execute(statement.replace("__EMBEDDING_DIMENSION__", dimension))
    for statement in INDEX_SQL:
        op.execute(statement)
    for statement in POST_TABLE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for table_name in DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
    for enum_name in reversed(tuple(ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
    op.execute("DROP FUNCTION IF EXISTS reject_source_snapshot_update()")
    op.execute("DROP FUNCTION IF EXISTS protect_methodology_version_config()")
    # Extensions may be shared by other schemas, so downgrade deliberately leaves them installed.
