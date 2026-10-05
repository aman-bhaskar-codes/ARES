"""M11 validated visual datasets, specs, and evidence lineage.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
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
        "visualization_datasets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dataset_kind", sa.String(40), nullable=False),
        sa.Column("dataset_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("lineage_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "dataset_kind", "content_hash", name="uq_visualization_dataset_content"),
    )
    for column in ("workspace_id", "run_id", "dataset_kind", "content_hash"):
        op.create_index(f"ix_visualization_datasets_{column}", "visualization_datasets", [column])

    op.create_table(
        "visualizations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("visualization_datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("approved_spec_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("export_metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "kind", "spec_hash", name="uq_visualization_spec"),
    )
    for column in ("workspace_id", "run_id", "dataset_id", "kind", "spec_hash"):
        op.create_index(f"ix_visualizations_{column}", "visualizations", [column])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("visualization_datasets", "visualizations"):
            _workspace_rls(table_name)
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT ON visualization_datasets, visualizations TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON visualization_datasets, visualizations TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("visualizations", "visualization_datasets"):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
    op.drop_table("visualizations")
    op.drop_table("visualization_datasets")
