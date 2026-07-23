"""Add the article-title input mode while preserving historical URL records.

Revision ID: 20260723_0006
Revises: 20260720_0005
"""

from alembic import op


revision = "20260723_0006"
down_revision = "20260720_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE input_type ADD VALUE IF NOT EXISTS 'ARTICLE_TITLE'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely. Keeping this value lets
    # archived runs remain readable and reproducible during a downgrade.
    pass
