"""Add durable ownership metadata for validated private uploads.

Revision ID: 20260703_0003
Revises: 20260702_0002
"""

from alembic import op

revision = "20260703_0003"
down_revision = "20260702_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE uploads (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            object_path text NOT NULL UNIQUE,
            original_filename varchar(255) NOT NULL,
            content_type varchar(100) NOT NULL,
            size_bytes integer NOT NULL CONSTRAINT ck_uploads_positive_size CHECK (size_bytes > 0),
            content_hash varchar(64) NOT NULL,
            claimed_at timestamptz,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_uploads_user_created ON uploads (user_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS uploads")
