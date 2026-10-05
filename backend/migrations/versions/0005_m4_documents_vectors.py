"""M4 document provenance, persistent chunks, exports, and pgvector sidecar

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("document_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("source_kind", sa.String(32), nullable=False, server_default="web"))
        batch.add_column(sa.Column("canonical_identifier", sa.String(512), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_sources_source_kind", ["source_kind"])
        batch.create_index("ix_sources_canonical_identifier", ["canonical_identifier"])

    with op.batch_alter_table("document_versions") as batch:
        batch.add_column(sa.Column("page_map", sa.JSON(), nullable=True))

    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("page_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("page_end", sa.Integer(), nullable=True))

    with op.batch_alter_table("user_documents") as batch:
        batch.add_column(sa.Column("blob_key", sa.Text(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(32), nullable=False, server_default="ready"))
        batch.add_column(sa.Column("page_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("page_map", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("warnings", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("parser_version", sa.String(80), nullable=True))
        batch.create_index("ix_user_documents_status", ["status"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("user_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    op.create_table(
        "document_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chunk_id", "model_id", "dimensions", name="uq_chunk_embedding_identity"),
    )
    op.create_index("ix_document_embeddings_chunk_id", "document_embeddings", ["chunk_id"])
    op.create_index("ix_document_embeddings_model_id", "document_embeddings", ["model_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(24), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_content_hash", "artifacts", ["content_hash"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Exact vector search first. No HNSW/IVFFlat index is created until a measured
        # retrieval/latency benchmark justifies approximate search.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            """
            CREATE TABLE document_embeddings_pg (
                chunk_id UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
                model_id VARCHAR(160) NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding vector NOT NULL,
                PRIMARY KEY (chunk_id, model_id, dimensions)
            )
            """
        )
        op.execute("CREATE INDEX ix_document_embeddings_pg_model ON document_embeddings_pg (model_id, dimensions)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS document_embeddings_pg")

    op.drop_index("ix_artifacts_content_hash", table_name="artifacts")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_document_embeddings_model_id", table_name="document_embeddings")
    op.drop_index("ix_document_embeddings_chunk_id", table_name="document_embeddings")
    op.drop_table("document_embeddings")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    with op.batch_alter_table("user_documents") as batch:
        batch.drop_index("ix_user_documents_status")
        batch.drop_column("parser_version")
        batch.drop_column("warnings")
        batch.drop_column("page_map")
        batch.drop_column("page_count")
        batch.drop_column("status")
        batch.drop_column("blob_key")

    with op.batch_alter_table("evidence") as batch:
        batch.drop_column("page_end")
        batch.drop_column("page_start")

    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("page_map")

    with op.batch_alter_table("sources") as batch:
        batch.drop_index("ix_sources_canonical_identifier")
        batch.drop_index("ix_sources_source_kind")
        batch.drop_column("published_at")
        batch.drop_column("canonical_identifier")
        batch.drop_column("source_kind")

    with op.batch_alter_table("runs") as batch:
        batch.drop_column("document_ids")
