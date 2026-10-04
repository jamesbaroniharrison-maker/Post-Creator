"""topic angles, opening scores, voided-post tally, opinion prompts

Revision ID: d6a2f9b31c58
Revises: c41d8e2a7f15
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'd6a2f9b31c58'
down_revision: Union[str, Sequence[str], None] = 'c41d8e2a7f15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('post') as batch:
        batch.add_column(sa.Column('topic_angle', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch.add_column(sa.Column('opening_score', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('opening_note', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table('topicbank') as batch:
        batch.add_column(sa.Column('topic_angle', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    op.create_table('voidedpost',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('drafted_at', sa.DateTime(), nullable=True),
    sa.Column('voided_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('opinionprompt',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bank_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('answer_text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('answered_at', sa.DateTime(), nullable=True),
    sa.Column('skipped_at', sa.DateTime(), nullable=True),
    sa.Column('post_id', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )

    # Tag the topic bank rows that already exist (keyword classifier, no model call).
    try:
        from linkedin_content_engine.angles import classify_angle
    except ImportError:
        return
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, category, summary, source_title FROM topicbank")).fetchall()
    for row_id, category, summary, title in rows:
        conn.execute(
            sa.text("UPDATE topicbank SET topic_angle = :a WHERE id = :id"),
            {"a": classify_angle(f"{title or ''} {summary or ''}", category), "id": row_id},
        )
    rows = conn.execute(sa.text("SELECT id, post_type, draft_text FROM post")).fetchall()
    for row_id, post_type, text in rows:
        if post_type in ("ai_commentary", "market_commentary"):
            conn.execute(
                sa.text("UPDATE post SET topic_angle = :a WHERE id = :id"),
                {"a": classify_angle(text or "", "market" if post_type == "market_commentary" else "ai"), "id": row_id},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('opinionprompt')
    op.drop_table('voidedpost')
    with op.batch_alter_table('topicbank') as batch:
        batch.drop_column('topic_angle')
    with op.batch_alter_table('post') as batch:
        batch.drop_column('opening_note')
        batch.drop_column('opening_score')
        batch.drop_column('topic_angle')
