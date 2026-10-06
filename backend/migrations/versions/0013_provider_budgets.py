"""provider budgets

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_usage") as batch_op:
        batch_op.add_column(sa.Column("output_tokens_reserved", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("cost_usd_reserved", sa.Float(), nullable=False, server_default="0.0"))
        batch_op.add_column(sa.Column("cost_usd_actual", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_usage") as batch_op:
        batch_op.drop_column("cost_usd_actual")
        batch_op.drop_column("cost_usd_reserved")
        batch_op.drop_column("output_tokens_reserved")
