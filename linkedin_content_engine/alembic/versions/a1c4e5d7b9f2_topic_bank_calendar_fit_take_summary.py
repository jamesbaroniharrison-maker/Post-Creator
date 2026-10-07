"""topic_bank_calendar_fit_take_summary

Revision ID: a1c4e5d7b9f2
Revises: d6a2f9b31c58
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'a1c4e5d7b9f2'
down_revision: Union[str, Sequence[str], None] = 'd6a2f9b31c58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('topicbank', schema=None) as batch_op:
        batch_op.add_column(sa.Column('calendar_link_note', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('rejected_event_ids', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('user_take', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('llm_summary', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('topicbank', schema=None) as batch_op:
        batch_op.drop_column('llm_summary')
        batch_op.drop_column('user_take')
        batch_op.drop_column('rejected_event_ids')
        batch_op.drop_column('calendar_link_note')
