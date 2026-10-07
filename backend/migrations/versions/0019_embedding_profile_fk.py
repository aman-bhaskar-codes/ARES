"""Repair the embedding profile foreign key introduced in 0015.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('document_embeddings') as batch:
        batch.drop_constraint('fk_doc_embed_profile', type_='foreignkey')
        batch.create_foreign_key('fk_doc_embed_profile', 'retrieval_profiles',
                                 ['profile_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('document_embeddings') as batch:
        batch.drop_constraint('fk_doc_embed_profile', type_='foreignkey')
        batch.create_foreign_key('fk_doc_embed_profile', 'document_embeddings',
                                 ['profile_id'], ['id'], ondelete='CASCADE')
