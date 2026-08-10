"""Add authority-first discovery and source-selection provenance.

Revision ID: 20260809_0008
Revises: 20260801_0007
"""

from alembic import op


revision = "20260809_0008"
down_revision = "20260801_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS "
        "ck_search_queries_discovery_phase"
    )
    op.execute(
        "ALTER TABLE search_queries ADD CONSTRAINT ck_search_queries_discovery_phase "
        "CHECK (discovery_phase IN ('authority_preflight', 'phase_one', 'phase_two'))"
    )
    op.execute("ALTER TABLE search_queries ADD COLUMN authority_profile_version varchar(100)")
    op.execute("ALTER TABLE search_queries ADD COLUMN authority_registry_version varchar(100)")
    op.execute("ALTER TABLE search_queries ADD COLUMN source_role varchar(100)")
    op.execute("ALTER TABLE search_queries ADD COLUMN domain_restriction varchar(255)")
    op.execute(
        "ALTER TABLE run_sources ADD COLUMN selection_metadata jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM search_queries WHERE discovery_phase = 'authority_preflight' "
        "OR generated_by_node LIKE 'authority_preflight:%'"
    )
    op.execute("ALTER TABLE run_sources DROP COLUMN IF EXISTS selection_metadata")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS domain_restriction")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS source_role")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS authority_registry_version")
    op.execute("ALTER TABLE search_queries DROP COLUMN IF EXISTS authority_profile_version")
    op.execute(
        "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS "
        "ck_search_queries_discovery_phase"
    )
    op.execute(
        "ALTER TABLE search_queries ADD CONSTRAINT ck_search_queries_discovery_phase "
        "CHECK (discovery_phase IN ('phase_one', 'phase_two'))"
    )
