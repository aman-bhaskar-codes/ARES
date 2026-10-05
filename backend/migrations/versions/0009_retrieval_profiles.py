"""M08 indexed lexical retrieval and embedding profile identity.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("profile_key", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("model_revision", sa.String(160), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("normalization", sa.String(40), nullable=False, server_default="l2"),
        sa.Column("pooling", sa.String(40), nullable=False, server_default="model_default"),
        sa.Column("query_prefix", sa.String(80), nullable=False, server_default=""),
        sa.Column("passage_prefix", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_key", name="uq_embedding_profiles_profile_key"),
    )
    op.create_index("ix_embedding_profiles_profile_key", "embedding_profiles", ["profile_key"], unique=True)

    with op.batch_alter_table("user_documents") as batch:
        batch.add_column(sa.Column("semantic_ready", sa.Boolean(), nullable=False, server_default=sa.false()))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Keep search_vector derived from the authoritative chunk text. The explicit
        # 'simple' configuration avoids hidden language stemming assumptions and gives
        # deterministic multilingual token handling for the first indexed baseline.
        op.execute(
            "CREATE INDEX ix_document_chunks_fts_simple ON document_chunks "
            "USING GIN (to_tsvector('simple', coalesce(text, '')))"
        )
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT ON embedding_profiles TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON embedding_profiles TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_fts_simple")

    with op.batch_alter_table("user_documents") as batch:
        batch.drop_column("semantic_ready")

    op.drop_index("ix_embedding_profiles_profile_key", table_name="embedding_profiles")
    op.drop_table("embedding_profiles")
