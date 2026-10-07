"""M13-04 Document embeddings PG profile

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # We must alter the document_embeddings_pg table and add profile_id
    op.execute("ALTER TABLE document_embeddings_pg ADD COLUMN profile_id UUID NULL;")
    op.execute("ALTER TABLE document_embeddings_pg ADD CONSTRAINT fk_doc_embed_pg_profile FOREIGN KEY (profile_id) REFERENCES retrieval_profiles (id) ON DELETE CASCADE;")
    op.execute("CREATE INDEX ix_document_embeddings_pg_profile_id ON document_embeddings_pg (profile_id);")
    
    # We must recreate the unique constraint to include profile_id? Wait! 
    # In store_chunk_embeddings we do ON CONFLICT (chunk_id, model_id, dimensions)
    # So the unique constraint is on (chunk_id, model_id, dimensions). We don't necessarily need to change it if we just want multiple models. 
    # Actually wait, multiple profiles might embed the same chunk with different dimensions or something?
    # No, the unique constraint is already chunk_id, model_id, dimensions. We just added profile_id.

def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX ix_document_embeddings_pg_profile_id;")
    op.execute("ALTER TABLE document_embeddings_pg DROP CONSTRAINT fk_doc_embed_pg_profile;")
    op.execute("ALTER TABLE document_embeddings_pg DROP COLUMN profile_id;")
