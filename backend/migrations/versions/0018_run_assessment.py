"""M13-05 Run assessment and outline

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("outline", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("assessment", sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column("runs", "assessment")
    op.drop_column("runs", "outline")
