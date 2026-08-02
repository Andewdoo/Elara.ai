"""Add adaptive Brave Search execution provenance.

Revision ID: 20260801_0007
Revises: 20260723_0006
"""

from alembic import op


revision = "20260801_0007"
down_revision = "20260723_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE search_queries ADD COLUMN discovery_phase varchar(20) "
        "NOT NULL DEFAULT 'phase_one'"
    )
    op.execute(
        "ALTER TABLE search_queries ADD COLUMN execution_status varchar(20) "
        "NOT NULL DEFAULT 'planned'"
    )
    op.execute(
        "ALTER TABLE search_queries ADD COLUMN network_attempt_count integer "
        "NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE search_queries ADD COLUMN skip_reason varchar(100)")
    op.execute(
        "ALTER TABLE search_queries ADD COLUMN policy_version varchar(100) "
        "NOT NULL DEFAULT 'legacy-search-v1'"
    )
    op.execute(
        "UPDATE search_queries SET execution_status = 'executed', network_attempt_count = 1 "
        "WHERE executed_at IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE search_queries ALTER COLUMN policy_version "
        "SET DEFAULT 'adaptive-search-v1'"
    )
    op.execute(
        "ALTER TABLE search_queries ADD CONSTRAINT ck_search_queries_discovery_phase "
        "CHECK (discovery_phase IN ('phase_one', 'phase_two'))"
    )
    op.execute(
        "ALTER TABLE search_queries ADD CONSTRAINT ck_search_queries_execution_status "
        "CHECK (execution_status IN ('planned', 'executed', 'cache_hit', 'not_needed'))"
    )
    op.execute(
        "ALTER TABLE search_queries ADD CONSTRAINT ck_search_queries_network_attempt_count "
        "CHECK (network_attempt_count >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS "
        "ck_search_queries_network_attempt_count"
    )
    op.execute(
        "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS "
        "ck_search_queries_execution_status"
    )
    op.execute(
        "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS "
        "ck_search_queries_discovery_phase"
    )
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS policy_version")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS skip_reason")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS network_attempt_count")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS execution_status")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS discovery_phase")
