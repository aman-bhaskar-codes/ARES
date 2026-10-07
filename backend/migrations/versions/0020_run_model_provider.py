"""Persist the answer provider selected for each run."""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    if 'model_provider' in {column['name'] for column in sa.inspect(op.get_bind()).get_columns('runs')}:
        return
    op.add_column("runs", sa.Column("model_provider", sa.String(24), nullable=True))


def downgrade():
    op.drop_column("runs", "model_provider")
