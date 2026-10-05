"""M10 research caching, facet coverage, source origins, and evidence-edge semantics.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
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
        "research_cache",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False, server_default="m10-v1"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "namespace", "cache_key", "policy_version", name="uq_research_cache_identity"
        ),
    )
    for column in ("workspace_id", "namespace", "cache_key", "expires_at"):
        op.create_index(f"ix_research_cache_{column}", "research_cache", [column])

    op.create_table(
        "facet_coverage",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("facet_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="missing"),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("conflicting_evidence_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("checker_method", sa.String(64), nullable=False, server_default="deterministic"),
        sa.Column("checker_version", sa.String(32), nullable=False, server_default="m10-v1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "facet_key", name="uq_facet_coverage_run_key"),
    )
    for column in ("workspace_id", "run_id", "status"):
        op.create_index(f"ix_facet_coverage_{column}", "facet_coverage", [column])

    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("origin_group_id", sa.Uuid(), nullable=True))
        batch.create_index("ix_sources_origin_group_id", ["origin_group_id"])

    with op.batch_alter_table("claim_evidence") as batch:
        batch.add_column(sa.Column("rationale", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("checker_method", sa.String(64), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("checker_version", sa.String(32), nullable=False, server_default="legacy"))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("research_cache", "facet_coverage"):
            _workspace_rls(table_name)
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT ON research_cache, facet_coverage TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON research_cache, facet_coverage TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("facet_coverage", "research_cache"):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    with op.batch_alter_table("claim_evidence") as batch:
        batch.drop_column("checker_version")
        batch.drop_column("checker_method")
        batch.drop_column("rationale")

    with op.batch_alter_table("sources") as batch:
        batch.drop_index("ix_sources_origin_group_id")
        batch.drop_column("origin_group_id")

    op.drop_table("facet_coverage")
    op.drop_table("research_cache")
