"""M13-05 Retrieval Trace

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("query_hash", sa.String(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("candidate_ids", sa.JSON().with_variant(sa.ARRAY(sa.Uuid()), "postgresql"), nullable=False),
        sa.Column("candidate_ranks", sa.JSON().with_variant(sa.ARRAY(sa.Float()), "postgresql"), nullable=False),
        sa.Column("selected_packet_ids", sa.JSON().with_variant(sa.ARRAY(sa.Uuid()), "postgresql"), nullable=False),
        sa.Column("stage_times", sa.JSON(), nullable=False),
        sa.Column("cache_freshness", sa.String(), nullable=False),
        sa.Column("coverage_gaps", sa.JSON().with_variant(sa.ARRAY(sa.String()), "postgresql"), nullable=False),
        sa.Column("policy_revision", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["retrieval_profiles.id"], name="fk_retrieval_traces_profile_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_retrieval_traces_workspace_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retrieval_traces_created_at", "retrieval_traces", ["created_at"], unique=False
    )
    op.create_index(
        "ix_retrieval_traces_profile_id", "retrieval_traces", ["profile_id"], unique=False
    )
    op.create_index(
        "ix_retrieval_traces_workspace_id", "retrieval_traces", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_traces_workspace_id", table_name="retrieval_traces")
    op.drop_index("ix_retrieval_traces_profile_id", table_name="retrieval_traces")
    op.drop_index("ix_retrieval_traces_created_at", table_name="retrieval_traces")
    op.drop_table("retrieval_traces")
