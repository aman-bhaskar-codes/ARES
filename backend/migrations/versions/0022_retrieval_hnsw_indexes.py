"""Add HNSW index on document embeddings for accelerated vector retrieval.

pgvector HNSW requires columns with explicit dimensions.  The original schema
created the column as ``vector`` (dimensionless).  We cast to ``vector(384)``
first (matching the default bge-small-en-v1.5 embedding size) before building
the index.
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# Must match Settings.local_embedding_dimensions (384 for bge-small-en-v1.5).
_EMBEDDING_DIM = 384


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # 1. Cast dimensionless vector → vector(384) so HNSW can be built.
    op.execute(
        f"""
        ALTER TABLE document_embeddings_pg
        ALTER COLUMN embedding TYPE vector({_EMBEDDING_DIM})
        USING embedding::vector({_EMBEDDING_DIM})
        """
    )

    # 2. Build HNSW index for sub-linear ANN lookup.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_pg_hnsw
        ON document_embeddings_pg USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_pg_hnsw")
    # Revert typed column back to dimensionless vector.
    op.execute(
        "ALTER TABLE document_embeddings_pg ALTER COLUMN embedding TYPE vector USING embedding::vector"
    )
