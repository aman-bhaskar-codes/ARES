"""M6 multi-tenant identity, sessions, audit, worker fleet and RLS

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SYSTEM_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
SYSTEM_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject", name="uq_users_subject"),
    )
    op.create_index("ix_users_subject", "users", ["subject"], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_workspace_id", "sessions", ["workspace_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "oidc_states",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("code_verifier", sa.String(256), nullable=False),
        sa.Column("nonce", sa.String(256), nullable=False),
        sa.Column("return_path", sa.String(1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("state_hash", name="uq_oidc_states_state_hash"),
    )
    op.create_index("ix_oidc_states_state_hash", "oidc_states", ["state_hash"], unique=True)
    op.create_index("ix_oidc_states_expires_at", "oidc_states", ["expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(96), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    op.create_table(
        "worker_instances",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("instance_name", sa.String(160), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_worker_instances_state", "worker_instances", ["state"])
    op.create_index("ix_worker_instances_last_seen_at", "worker_instances", ["last_seen_at"])

    now = datetime.now(UTC)
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()), sa.column("subject", sa.String()), sa.column("email", sa.String()),
        sa.column("display_name", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    workspaces = sa.table(
        "workspaces", sa.column("id", sa.Uuid()), sa.column("name", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    memberships = sa.table(
        "workspace_memberships", sa.column("id", sa.Uuid()), sa.column("workspace_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()), sa.column("role", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(users, [{
        "id": SYSTEM_USER_ID, "subject": "local:system", "email": None,
        "display_name": "Local ARES", "created_at": now, "updated_at": now,
    }])
    op.bulk_insert(workspaces, [{"id": SYSTEM_WORKSPACE_ID, "name": "Local workspace", "created_at": now}])
    op.bulk_insert(memberships, [{
        "id": UUID("00000000-0000-4000-8000-000000000003"),
        "workspace_id": SYSTEM_WORKSPACE_ID, "user_id": SYSTEM_USER_ID, "role": "owner", "created_at": now,
    }])

    for table_name in ("conversations", "runs", "user_documents"):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("workspace_id", sa.Uuid(), nullable=True))
            batch.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))

    bind = op.get_bind()
    for table_name in ("conversations", "runs", "user_documents"):
        statement = sa.text(
            f"UPDATE {table_name} SET workspace_id=:workspace_id, created_by_user_id=:user_id "
            "WHERE workspace_id IS NULL OR created_by_user_id IS NULL"
        ).bindparams(
            sa.bindparam("workspace_id", type_=sa.Uuid()),
            sa.bindparam("user_id", type_=sa.Uuid()),
        )
        bind.execute(statement, {"workspace_id": SYSTEM_WORKSPACE_ID, "user_id": SYSTEM_USER_ID})

    for table_name in ("conversations", "runs", "user_documents"):
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column("workspace_id", existing_type=sa.Uuid(), nullable=False)
            batch.alter_column("created_by_user_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(f"fk_{table_name}_workspace_id", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
            batch.create_foreign_key(f"fk_{table_name}_created_by_user_id", "users", ["created_by_user_id"], ["id"], ondelete="RESTRICT")
            batch.create_index(f"ix_{table_name}_workspace_id", ["workspace_id"])
            batch.create_index(f"ix_{table_name}_created_by_user_id", ["created_by_user_id"])

    if bind.dialect.name == "postgresql":
        _install_postgres_rls()


def _install_postgres_rls() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ares_current_workspace_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ares_global_active_run_count() RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT count(*) FROM public.runs
            WHERE status NOT IN ('completed', 'partial', 'failed', 'cancelled')
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ares_global_active_run_count() FROM PUBLIC")

    direct = {
        "conversations": "workspace_id",
        "runs": "workspace_id",
        "user_documents": "workspace_id",
        "audit_events": "workspace_id",
    }
    for table_name, column in direct.items():
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_workspace_isolation ON {table_name} "
            f"USING ({column} = ares_current_workspace_id()) "
            f"WITH CHECK ({column} = ares_current_workspace_id())"
        )

    op.execute(
        "CREATE POLICY audit_events_anonymous_insert ON audit_events FOR INSERT "
        "WITH CHECK (workspace_id IS NULL AND user_id IS NULL)"
    )

    policies = {
        "jobs": "EXISTS (SELECT 1 FROM runs r WHERE r.id = jobs.run_id AND r.workspace_id = ares_current_workspace_id())",
        "run_events": "EXISTS (SELECT 1 FROM runs r WHERE r.id = run_events.run_id AND r.workspace_id = ares_current_workspace_id())",
        "sources": "EXISTS (SELECT 1 FROM runs r WHERE r.id = sources.run_id AND r.workspace_id = ares_current_workspace_id())",
        "evidence": "EXISTS (SELECT 1 FROM runs r WHERE r.id = evidence.run_id AND r.workspace_id = ares_current_workspace_id())",
        "claims": "EXISTS (SELECT 1 FROM runs r WHERE r.id = claims.run_id AND r.workspace_id = ares_current_workspace_id())",
        "artifacts": "EXISTS (SELECT 1 FROM runs r WHERE r.id = artifacts.run_id AND r.workspace_id = ares_current_workspace_id())",
        "document_versions": "EXISTS (SELECT 1 FROM sources s JOIN runs r ON r.id=s.run_id WHERE s.id=document_versions.source_id AND r.workspace_id=ares_current_workspace_id())",
        "claim_evidence": "EXISTS (SELECT 1 FROM claims c JOIN runs r ON r.id=c.run_id WHERE c.id=claim_evidence.claim_id AND r.workspace_id=ares_current_workspace_id())",
        "document_chunks": "EXISTS (SELECT 1 FROM user_documents d WHERE d.id=document_chunks.document_id AND d.workspace_id=ares_current_workspace_id())",
        "document_embeddings": "EXISTS (SELECT 1 FROM document_chunks c JOIN user_documents d ON d.id=c.document_id WHERE c.id=document_embeddings.chunk_id AND d.workspace_id=ares_current_workspace_id())",
    }
    for table_name, predicate in policies.items():
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_workspace_isolation ON {table_name} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    op.execute("ALTER TABLE document_embeddings_pg ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_embeddings_pg FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_embeddings_pg_workspace_isolation ON document_embeddings_pg
        USING (EXISTS (
            SELECT 1 FROM document_chunks c JOIN user_documents d ON d.id=c.document_id
            WHERE c.id=document_embeddings_pg.chunk_id AND d.workspace_id=ares_current_workspace_id()
        ))
        WITH CHECK (EXISTS (
            SELECT 1 FROM document_chunks c JOIN user_documents d ON d.id=c.document_id
            WHERE c.id=document_embeddings_pg.chunk_id AND d.workspace_id=ares_current_workspace_id()
        ))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in (
            "document_embeddings_pg", "document_embeddings", "document_chunks", "claim_evidence",
            "document_versions", "artifacts", "claims", "evidence", "sources", "run_events", "jobs",
            "audit_events", "user_documents", "runs", "conversations",
        ):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
        op.execute("DROP FUNCTION IF EXISTS ares_global_active_run_count()")
        op.execute("DROP FUNCTION IF EXISTS ares_current_workspace_id()")

    for table_name in ("user_documents", "runs", "conversations"):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(f"ix_{table_name}_created_by_user_id")
            batch.drop_index(f"ix_{table_name}_workspace_id")
            batch.drop_constraint(f"fk_{table_name}_created_by_user_id", type_="foreignkey")
            batch.drop_constraint(f"fk_{table_name}_workspace_id", type_="foreignkey")
            batch.drop_column("created_by_user_id")
            batch.drop_column("workspace_id")

    op.drop_index("ix_worker_instances_last_seen_at", table_name="worker_instances")
    op.drop_index("ix_worker_instances_state", table_name="worker_instances")
    op.drop_table("worker_instances")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_oidc_states_expires_at", table_name="oidc_states")
    op.drop_index("ix_oidc_states_state_hash", table_name="oidc_states")
    op.drop_table("oidc_states")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_workspace_id", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_table("workspaces")
    op.drop_index("ix_users_subject", table_name="users")
    op.drop_table("users")
