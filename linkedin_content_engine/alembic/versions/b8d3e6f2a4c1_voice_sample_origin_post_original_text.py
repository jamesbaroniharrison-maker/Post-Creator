"""voice_sample_origin_post_original_text

Revision ID: b8d3e6f2a4c1
Revises: a1c4e5d7b9f2
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b8d3e6f2a4c1'
down_revision: Union[str, Sequence[str], None] = 'a1c4e5d7b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('voicesample', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='own'))
        batch_op.add_column(sa.Column('origin_note', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.add_column(sa.Column('original_text', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('voice_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('voice_notes', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.drop_column('voice_notes')
        batch_op.drop_column('voice_score')
        batch_op.drop_column('original_text')
    with op.batch_alter_table('voicesample', schema=None) as batch_op:
        batch_op.drop_column('origin_note')
        batch_op.drop_column('origin')
