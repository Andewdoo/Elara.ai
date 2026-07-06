"""Durable publication, retention, sharing, deletion, and adjudication controls.

Revision ID: 20260706_0004
Revises: 20260703_0003
"""

from alembic import op

revision = "20260706_0004"
down_revision = "20260703_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE verification_runs ADD COLUMN deletion_requested_at timestamptz")
    op.execute("ALTER TABLE verification_runs ADD COLUMN deletion_status varchar(30) NOT NULL DEFAULT 'none'")
    op.execute("ALTER TABLE verification_runs ADD COLUMN legal_hold_until timestamptz")
    op.execute("ALTER TABLE verification_runs ADD COLUMN publication_state varchar(30) NOT NULL DEFAULT 'unreviewed'")
    op.execute("ALTER TABLE verification_runs ADD COLUMN publication_review_reason varchar(255)")
    op.execute("ALTER TABLE verification_runs ADD COLUMN publication_reviewed_by uuid REFERENCES users(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE verification_runs ADD COLUMN publication_reviewed_at timestamptz")
    op.execute("ALTER TABLE uploads ADD COLUMN expires_at timestamptz")
    op.execute("ALTER TABLE uploads ADD COLUMN deleted_at timestamptz")
    op.execute("""
        CREATE TABLE report_shares (
            id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
            recipient_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scope varchar(40) NOT NULL CONSTRAINT ck_report_shares_scope
                CHECK (scope IN ('report', 'report_sources', 'report_sources_exports')),
            expires_at timestamptz NOT NULL, revoked_at timestamptz, created_at timestamptz NOT NULL,
            CONSTRAINT uq_report_shares_recipient UNIQUE (run_id, recipient_user_id)
        )
    """)
    op.execute("CREATE INDEX ix_report_shares_recipient_active ON report_shares (recipient_user_id, revoked_at, expires_at)")
    op.execute("""
        CREATE TABLE governance_decisions (
            id uuid PRIMARY KEY, feedback_id uuid NOT NULL REFERENCES user_feedback(id) ON DELETE RESTRICT,
            reviewer_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            prior_status varchar(50) NOT NULL, decision varchar(50) NOT NULL, rationale text NOT NULL,
            revised_run_id uuid REFERENCES verification_runs(id) ON DELETE RESTRICT,
            public_notice_required boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_governance_decisions_feedback_created ON governance_decisions (feedback_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS governance_decisions")
    op.execute("DROP TABLE IF EXISTS report_shares")
    op.execute("ALTER TABLE uploads DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE uploads DROP COLUMN IF EXISTS expires_at")
    for column in ("publication_reviewed_at", "publication_reviewed_by", "publication_review_reason", "publication_state", "legal_hold_until", "deletion_status", "deletion_requested_at"):
        op.execute(f"ALTER TABLE verification_runs DROP COLUMN IF EXISTS {column}")
