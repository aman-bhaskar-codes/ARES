"""Add plugins and related_questions columns to runs."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('runs')}
    if 'plugins' not in existing:
        op.add_column("runs", sa.Column("plugins", sa.JSON(), nullable=True))
    if 'related_questions' not in existing:
        op.add_column("runs", sa.Column("related_questions", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("runs", "plugins")
    op.drop_column("runs", "related_questions")
