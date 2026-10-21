"""Add memory system tiers: episodic memory, semantic memory facts, and user preferences.

Revision ID: 0023
Revises: 0022
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()

    # 1. Episodic Memory: summaries of past runs and conversations
    if "memory_episodes" not in tables:
        op.create_table(
            "memory_episodes",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("key_findings", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_memory_episodes_workspace_id", "memory_episodes", ["workspace_id"])
        op.create_index("ix_memory_episodes_user_id", "memory_episodes", ["user_id"])
        op.create_index("ix_memory_episodes_created_at", "memory_episodes", ["created_at"])

    # 2. Semantic Memory: verified facts and entities with evidence and supersession links
    if "memory_facts" not in tables:
        op.create_table(
            "memory_facts",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("predicate", sa.String(100), nullable=False),
            sa.Column("fact", sa.Text(), nullable=False),
            sa.Column("evidence_source", sa.String(500), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("superseded_by_id", sa.Uuid(), sa.ForeignKey("memory_facts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_memory_facts_workspace_id", "memory_facts", ["workspace_id"])
        op.create_index("ix_memory_facts_user_id", "memory_facts", ["user_id"])
        op.create_index("ix_memory_facts_subject", "memory_facts", ["subject"])
        op.create_index("ix_memory_facts_status", "memory_facts", ["status"])

    # 3. Preference Memory: per-user research configurations and domain preferences
    if "memory_preferences" not in tables:
        op.create_table(
            "memory_preferences",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("depth", sa.String(32), nullable=False, server_default="standard"),
            sa.Column("preferred_domains", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("excluded_domains", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("tone", sa.String(32), nullable=False, server_default="academic"),
            sa.Column("custom_instructions", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_memory_preferences_workspace_user"),
        )
        op.create_index("ix_memory_preferences_workspace_id", "memory_preferences", ["workspace_id"])
        op.create_index("ix_memory_preferences_user_id", "memory_preferences", ["user_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Vector embeddings for episodic memory
        op.execute(
            """
            CREATE TABLE memory_episodes_pg (
                episode_id UUID NOT NULL REFERENCES memory_episodes(id) ON DELETE CASCADE,
                model_id VARCHAR(160) NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding vector(384) NOT NULL,
                PRIMARY KEY (episode_id, model_id, dimensions)
            )
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_memory_episodes_pg_hnsw
            ON memory_episodes_pg USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            """
        )

        # Full-text search index on episodic memory
        op.execute("CREATE INDEX ix_memory_episodes_fts ON memory_episodes USING gin (to_tsvector('simple', title || ' ' || summary))")
        op.execute("CREATE INDEX ix_memory_facts_fts ON memory_facts USING gin (to_tsvector('simple', subject || ' ' || fact))")

        # Row-Level Security on memory tables
        for table in ["memory_episodes", "memory_facts", "memory_preferences"]:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_workspace_isolation ON {table} "
                f"USING (workspace_id = ares_current_workspace_id()) "
                f"WITH CHECK (workspace_id = ares_current_workspace_id())"
            )

        op.execute("ALTER TABLE memory_episodes_pg ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE memory_episodes_pg FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY memory_episodes_pg_workspace_isolation ON memory_episodes_pg
            USING (EXISTS (
                SELECT 1 FROM memory_episodes e
                WHERE e.id = memory_episodes_pg.episode_id AND e.workspace_id = ares_current_workspace_id()
            ))
            WITH CHECK (EXISTS (
                SELECT 1 FROM memory_episodes e
                WHERE e.id = memory_episodes_pg.episode_id AND e.workspace_id = ares_current_workspace_id()
            ))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS memory_episodes_pg")
    op.drop_table("memory_preferences")
    op.drop_table("memory_facts")
    op.drop_table("memory_episodes")
