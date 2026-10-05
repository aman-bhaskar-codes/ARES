"""M08 durable assets, extraction versions, segments, tables and ingestion jobs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table_name}_workspace_isolation ON {table_name} "
        "USING (workspace_id = ares_current_workspace_id()) "
        "WITH CHECK (workspace_id = ares_current_workspace_id())"
    )


def upgrade() -> None:
    op.create_table(
        "asset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("original_blob_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="quarantined"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "created_by_user_id", "sha256", "mime_type", "status"):
        op.create_index(f"ix_asset_versions_{column}", "asset_versions", [column])

    op.create_table(
        "extraction_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parser_id", sa.String(80), nullable=False),
        sa.Column("parser_revision", sa.String(80), nullable=False),
        sa.Column("model_revision", sa.String(160), nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="processing"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("page_map", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "asset_version_id", "parser_id", "parser_revision", "config_hash",
            name="uq_extraction_version_identity",
        ),
    )
    op.create_index("ix_extraction_versions_workspace_id", "extraction_versions", ["workspace_id"])
    op.create_index("ix_extraction_versions_asset_version_id", "extraction_versions", ["asset_version_id"])
    op.create_index("ix_extraction_versions_status", "extraction_versions", ["status"])
    op.create_index("ix_extraction_versions_output_hash", "extraction_versions", ["output_hash"])

    op.create_table(
        "evidence_segments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extraction_version_id", sa.Uuid(), sa.ForeignKey("extraction_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("user_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("modality", sa.String(24), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("derivation_kind", sa.String(64), nullable=False, server_default="machine_extracted"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("origin_group_id", sa.Uuid(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "extraction_version_id", "document_id", "modality", "origin_group_id", "content_hash"):
        op.create_index(f"ix_evidence_segments_{column}", "evidence_segments", [column])

    op.create_table(
        "document_tables",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extraction_version_id", sa.Uuid(), sa.ForeignKey("extraction_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_key", sa.String(120), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("locator_json", sa.JSON(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("columns", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("extraction_version_id", "table_key", name="uq_document_table_key"),
    )
    op.create_index("ix_document_tables_workspace_id", "document_tables", ["workspace_id"])
    op.create_index("ix_document_tables_extraction_version_id", "document_tables", ["extraction_version_id"])

    op.create_table(
        "document_table_cells",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", sa.Uuid(), sa.ForeignKey("document_tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("evidence_segments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("row_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("column_span", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_value_json", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(80), nullable=True),
        sa.Column("is_header", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locator_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("table_id", "row_index", "column_index", name="uq_document_table_cell"),
    )
    op.create_index("ix_document_table_cells_workspace_id", "document_table_cells", ["workspace_id"])
    op.create_index("ix_document_table_cells_table_id", "document_table_cells", ["table_id"])
    op.create_index("ix_document_table_cells_segment_id", "document_table_cells", ["segment_id"])

    op.create_table(
        "asset_renditions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extraction_version_id", sa.Uuid(), sa.ForeignKey("extraction_versions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_version_id", "kind", "content_hash", name="uq_asset_rendition"),
    )
    for column in ("workspace_id", "asset_version_id", "extraction_version_id", "content_hash"):
        op.create_index(f"ix_asset_renditions_{column}", "asset_renditions", [column])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("user_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("lexical_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semantic_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in (
        "workspace_id", "created_by_user_id", "asset_version_id", "document_id", "status", "stage",
        "lease_token", "leased_until", "created_at",
    ):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])

    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ingestion_id", sa.Uuid(), sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ingestion_id", "seq", name="uq_ingestion_event_seq"),
    )
    for column in ("workspace_id", "ingestion_id", "event_type"):
        op.create_index(f"ix_ingestion_events_{column}", "ingestion_events", [column])

    with op.batch_alter_table("user_documents") as batch:
        batch.add_column(sa.Column("asset_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("lexical_ready", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_foreign_key(
            "fk_user_documents_asset_version_id_asset_versions", "asset_versions",
            ["asset_version_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_user_documents_asset_version_id", ["asset_version_id"])

    with op.batch_alter_table("document_chunks") as batch:
        batch.add_column(sa.Column("evidence_segment_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_document_chunks_evidence_segment_id_evidence_segments", "evidence_segments",
            ["evidence_segment_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_document_chunks_evidence_segment_id", ["evidence_segment_id"])

    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("segment_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_segment_id_evidence_segments", "evidence_segments",
            ["segment_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_evidence_segment_id", ["segment_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in (
            "asset_versions", "extraction_versions", "evidence_segments", "document_tables",
            "document_table_cells", "asset_renditions", "ingestion_jobs", "ingestion_events",
        ):
            _workspace_rls(table_name)

        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT, INSERT, DELETE ON asset_versions TO ares_api;
                GRANT SELECT, INSERT, UPDATE ON ingestion_jobs TO ares_api;
                GRANT SELECT, INSERT ON ingestion_events TO ares_api;
                GRANT SELECT ON extraction_versions, evidence_segments, document_tables,
                  document_table_cells, asset_renditions TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON
                  asset_versions, extraction_versions, evidence_segments, document_tables,
                  document_table_cells, asset_renditions, ingestion_jobs, ingestion_events
                TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in (
            "ingestion_events", "ingestion_jobs", "asset_renditions", "document_table_cells",
            "document_tables", "evidence_segments", "extraction_versions", "asset_versions",
        ):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    with op.batch_alter_table("evidence") as batch:
        batch.drop_index("ix_evidence_segment_id")
        batch.drop_constraint("fk_evidence_segment_id_evidence_segments", type_="foreignkey")
        batch.drop_column("segment_id")

    with op.batch_alter_table("document_chunks") as batch:
        batch.drop_index("ix_document_chunks_evidence_segment_id")
        batch.drop_constraint("fk_document_chunks_evidence_segment_id_evidence_segments", type_="foreignkey")
        batch.drop_column("evidence_segment_id")

    with op.batch_alter_table("user_documents") as batch:
        batch.drop_index("ix_user_documents_asset_version_id")
        batch.drop_constraint("fk_user_documents_asset_version_id_asset_versions", type_="foreignkey")
        batch.drop_column("lexical_ready")
        batch.drop_column("asset_version_id")

    for table_name in (
        "ingestion_events", "ingestion_jobs", "asset_renditions", "document_table_cells",
        "document_tables", "evidence_segments", "extraction_versions", "asset_versions",
    ):
        op.drop_table(table_name)
