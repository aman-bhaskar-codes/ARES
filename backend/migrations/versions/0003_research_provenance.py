"""research provenance and document versions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("provider", sa.String(64), nullable=False, server_default="web"))
    op.add_column("sources", sa.Column("discovery_rank", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("snippet", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("extraction_method", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_versions_source_id", "document_versions", ["source_id"])
    op.create_index("ix_document_versions_content_hash", "document_versions", ["content_hash"])
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("document_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("char_start", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("char_end", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_document_version",
            "document_versions",
            ["document_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_evidence_document_version_id", ["document_version_id"])


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.drop_index("ix_evidence_document_version_id")
        batch.drop_constraint("fk_evidence_document_version", type_="foreignkey")
        batch.drop_column("char_end")
        batch.drop_column("char_start")
        batch.drop_column("document_version_id")
    op.drop_index("ix_document_versions_content_hash", table_name="document_versions")
    op.drop_index("ix_document_versions_source_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_column("sources", "snippet")
    op.drop_column("sources", "discovery_rank")
    op.drop_column("sources", "provider")
