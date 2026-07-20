"""Store safe internal diagnostics for terminal verification failures.

Revision ID: 20260720_0005
Revises: 20260706_0004
"""

from alembic import op


revision = "20260720_0005"
down_revision = "20260706_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE verification_runs ADD COLUMN internal_failure_detail text")


def downgrade() -> None:
    op.execute("ALTER TABLE verification_runs DROP COLUMN IF EXISTS internal_failure_detail")
