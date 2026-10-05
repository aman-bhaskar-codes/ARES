"""serialize provider quota reservations

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_quota_locks",
        sa.Column("provider", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(128), primary_key=True),
        sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_quota_locks")
