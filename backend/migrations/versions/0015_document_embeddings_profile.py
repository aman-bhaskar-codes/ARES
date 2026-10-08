"""M13-02 Document embeddings profile FK

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add profile_id to document_embeddings
    with op.batch_alter_table("document_embeddings") as batch:
        batch.add_column(sa.Column("profile_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_doc_embed_profile", "document_embeddings", ["profile_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_document_embeddings_profile_id", ["profile_id"])

def downgrade() -> None:
    with op.batch_alter_table("document_embeddings") as batch:
        batch.drop_index("ix_document_embeddings_profile_id")
        batch.drop_constraint("fk_doc_embed_profile", type_="foreignkey")
        batch.drop_column("profile_id")
