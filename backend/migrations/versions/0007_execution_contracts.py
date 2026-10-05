"""M07 execution contracts, assessment metadata, checkpoints and resource leases.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("date_window", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("budget_version", sa.String(32), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("usage_ledger", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_runs_deadline_at", ["deadline_at"])

    # Existing events remain authoritative. Backfill the denormalized stream cursor so
    # upgraded saved runs can resume/replay without fabricating sequence history.
    op.execute(
        "UPDATE runs SET last_seq = COALESCE((SELECT MAX(run_events.seq) FROM run_events "
        "WHERE run_events.run_id = runs.id), 0)"
    )

    with op.batch_alter_table("claims") as batch:
        batch.add_column(sa.Column("checker_method", sa.String(64), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("checker_version", sa.String(32), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("assessment_state", sa.String(32), nullable=False, server_default="legacy"))
        batch.add_column(sa.Column("assessment_rationale", sa.Text(), nullable=False, server_default=""))

    with op.batch_alter_table("provider_usage") as batch:
        batch.add_column(sa.Column("run_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("input_tokens_actual", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("output_tokens_actual", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_provider_usage_run_id_runs", "runs", ["run_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_provider_usage_run_id", ["run_id"])

    op.create_table(
        "run_steps",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_key", sa.String(96), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="started"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "step_key", "input_hash", "schema_version", name="uq_run_step_identity"),
    )
    op.create_index("ix_run_steps_run_id", "run_steps", ["run_id"])
    op.create_index("ix_run_steps_workspace_id", "run_steps", ["workspace_id"])
    op.create_index("ix_run_steps_step_key", "run_steps", ["step_key"])
    op.create_index("ix_run_steps_status", "run_steps", ["status"])

    op.create_table(
        "resource_leases",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_key", sa.String(96), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_key", "slot", name="uq_resource_lease_slot"),
    )
    op.create_index("ix_resource_leases_workspace_id", "resource_leases", ["workspace_id"])
    op.create_index("ix_resource_leases_owner_run_id", "resource_leases", ["owner_run_id"])
    op.create_index("ix_resource_leases_resource_key", "resource_leases", ["resource_key"])
    op.create_index("ix_resource_leases_lease_token", "resource_leases", ["lease_token"])
    op.create_index("ix_resource_leases_leased_until", "resource_leases", ["leased_until"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("run_steps", "resource_leases"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table_name}_workspace_isolation ON {table_name} "
                "USING (workspace_id = ares_current_workspace_id()) "
                "WITH CHECK (workspace_id = ares_current_workspace_id())"
            )

        # New objects are deny-by-default. API does not need direct checkpoint/lease
        # access in M07; the worker owns these execution internals.
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON run_steps, resource_leases TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("resource_leases", "run_steps"):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    for name in (
        "ix_resource_leases_leased_until",
        "ix_resource_leases_lease_token",
        "ix_resource_leases_resource_key",
        "ix_resource_leases_owner_run_id",
        "ix_resource_leases_workspace_id",
    ):
        op.drop_index(name, table_name="resource_leases")
    op.drop_table("resource_leases")

    for name in ("ix_run_steps_status", "ix_run_steps_step_key", "ix_run_steps_workspace_id", "ix_run_steps_run_id"):
        op.drop_index(name, table_name="run_steps")
    op.drop_table("run_steps")

    with op.batch_alter_table("provider_usage") as batch:
        batch.drop_index("ix_provider_usage_run_id")
        batch.drop_constraint("fk_provider_usage_run_id_runs", type_="foreignkey")
        batch.drop_column("reconciled_at")
        batch.drop_column("output_tokens_actual")
        batch.drop_column("input_tokens_actual")
        batch.drop_column("run_id")

    with op.batch_alter_table("claims") as batch:
        batch.drop_column("assessment_rationale")
        batch.drop_column("assessment_state")
        batch.drop_column("checker_version")
        batch.drop_column("checker_method")

    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_deadline_at")
        batch.drop_column("last_seq")
        batch.drop_column("usage_ledger")
        batch.drop_column("budget_version")
        batch.drop_column("deadline_at")
        batch.drop_column("date_window")
