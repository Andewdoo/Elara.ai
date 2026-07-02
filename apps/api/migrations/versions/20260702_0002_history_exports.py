"""Add saved-report and soft-deletion lifecycle fields.

Revision ID: 20260702_0002
Revises: 20260626_0001
"""

from alembic import op

revision = "20260702_0002"
down_revision = "20260626_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE verification_runs ADD COLUMN saved_at timestamptz")
    op.execute("ALTER TABLE verification_runs ADD COLUMN deleted_at timestamptz")
    op.execute(
        "CREATE INDEX ix_verification_runs_owner_saved "
        "ON verification_runs (user_id, saved_at)"
    )
    op.execute(
        "ALTER TABLE user_feedback ADD CONSTRAINT ck_user_feedback_category "
        "CHECK (category IN ('CORRECTION', 'MISSED_EVIDENCE', 'APPEAL', 'BROKEN_CITATION'))"
    )
    op.execute(
        "ALTER TABLE exports ADD CONSTRAINT ck_exports_type CHECK (export_type IN ('JSON'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE exports DROP CONSTRAINT IF EXISTS ck_exports_type")
    op.execute(
        "ALTER TABLE user_feedback DROP CONSTRAINT IF EXISTS ck_user_feedback_category"
    )
    op.execute("DROP INDEX IF EXISTS ix_verification_runs_owner_saved")
    op.execute("ALTER TABLE verification_runs DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE verification_runs DROP COLUMN IF EXISTS saved_at")
