"""M13 retrieval profiles

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create retrieval_profiles table
    op.create_table(
        "retrieval_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("profile_key", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("artifact_digest", sa.String(160), nullable=False),
        sa.Column("tokenizer_version", sa.String(80), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(40), nullable=False, server_default="cosine"),
        sa.Column("language_coverage", sa.String(80), nullable=False, server_default="en"),
        sa.Column("chunk_policy", sa.String(120), nullable=False),
        sa.Column("extraction_revision", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_key", name="uq_retrieval_profiles_profile_key"),
    )
    op.create_index("ix_retrieval_profiles_profile_key", "retrieval_profiles", ["profile_key"], unique=True)

    # 2. Add adjacency columns to document_chunks
    with op.batch_alter_table("document_chunks") as batch:
        batch.add_column(sa.Column("parent_chunk_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("previous_chunk_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("next_chunk_id", sa.Uuid(), nullable=True))
        
        batch.create_foreign_key("fk_doc_chunks_parent", "document_chunks", ["parent_chunk_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_doc_chunks_prev", "document_chunks", ["previous_chunk_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_doc_chunks_next", "document_chunks", ["next_chunk_id"], ["id"], ondelete="SET NULL")
        
        batch.create_index("ix_document_chunks_parent_chunk_id", ["parent_chunk_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT ON retrieval_profiles TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON retrieval_profiles TO ares_worker;
              END IF;
            END $$
            """
        )

def downgrade() -> None:
    with op.batch_alter_table("document_chunks") as batch:
        batch.drop_index("ix_document_chunks_parent_chunk_id")
        batch.drop_constraint("fk_doc_chunks_parent", type_="foreignkey")
        batch.drop_constraint("fk_doc_chunks_prev", type_="foreignkey")
        batch.drop_constraint("fk_doc_chunks_next", type_="foreignkey")
        batch.drop_column("next_chunk_id")
        batch.drop_column("previous_chunk_id")
        batch.drop_column("parent_chunk_id")

    op.drop_index("ix_retrieval_profiles_profile_key", table_name="retrieval_profiles")
    op.drop_table("retrieval_profiles")
