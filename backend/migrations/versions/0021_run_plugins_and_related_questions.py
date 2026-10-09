"""Add plugins and related_questions columns to runs."""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("runs", sa.Column("plugins", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("related_questions", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("runs", "plugins")
    op.drop_column("runs", "related_questions")
