"""M09 audio/video track and sampled-frame metadata.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
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
    with op.batch_alter_table("asset_versions") as batch:
        batch.add_column(
            sa.Column("cloud_media_allowed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("media_metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )

    with op.batch_alter_table("worker_instances") as batch:
        batch.add_column(
            sa.Column("capabilities_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )

    op.create_table(
        "media_tracks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "extraction_version_id",
            sa.Uuid(),
            sa.ForeignKey("extraction_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("track_type", sa.String(16), nullable=False),
        sa.Column("stream_index", sa.Integer(), nullable=False),
        sa.Column("codec_name", sa.String(80), nullable=True),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("average_frame_rate", sa.String(40), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_version_id", "track_type", "stream_index", name="uq_media_track_identity"
        ),
    )
    for column in ("workspace_id", "asset_version_id", "extraction_version_id", "track_type"):
        op.create_index(f"ix_media_tracks_{column}", "media_tracks", [column])

    op.create_table(
        "media_frames",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "extraction_version_id",
            sa.Uuid(),
            sa.ForeignKey("extraction_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rendition_id", sa.Uuid(), sa.ForeignKey("asset_renditions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("presentation_time_ms", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("perceptual_hash", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_version_id", "presentation_time_ms", "content_hash", name="uq_media_frame_identity"
        ),
    )
    for column in (
        "workspace_id",
        "asset_version_id",
        "extraction_version_id",
        "rendition_id",
        "presentation_time_ms",
        "content_hash",
    ):
        op.create_index(f"ix_media_frames_{column}", "media_frames", [column])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("media_tracks", "media_frames"):
            _workspace_rls(table_name)
        op.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
                GRANT SELECT ON media_tracks, media_frames TO ares_api;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON media_tracks, media_frames TO ares_worker;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("media_frames", "media_tracks"):
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    op.drop_table("media_frames")
    op.drop_table("media_tracks")

    with op.batch_alter_table("worker_instances") as batch:
        batch.drop_column("capabilities_json")

    with op.batch_alter_table("asset_versions") as batch:
        batch.drop_column("media_metadata_json")
        batch.drop_column("cloud_media_allowed")
