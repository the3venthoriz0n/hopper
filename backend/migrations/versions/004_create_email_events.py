"""Create email_events table

Revision ID: 004
Revises: 003
Create Date: 2025-01-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('resend_event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('email_id', sa.String(length=255), nullable=True),
        sa.Column('to_email', sa.String(length=255), nullable=True),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_events_id', 'email_events', ['id'])
    op.create_index('ix_email_events_resend_event_id', 'email_events', ['resend_event_id'])
    op.create_index('ix_email_events_event_type', 'email_events', ['event_type'])
    op.create_index('ix_email_events_email_id', 'email_events', ['email_id'])
    op.create_index('ix_email_events_to_email', 'email_events', ['to_email'])
    op.create_unique_constraint('uq_email_events_resend_event_id', 'email_events', ['resend_event_id'])


def downgrade() -> None:
    op.drop_constraint('uq_email_events_resend_event_id', 'email_events', type_='unique')
    op.drop_index('ix_email_events_to_email', table_name='email_events')
    op.drop_index('ix_email_events_email_id', table_name='email_events')
    op.drop_index('ix_email_events_event_type', table_name='email_events')
    op.drop_index('ix_email_events_resend_event_id', table_name='email_events')
    op.drop_index('ix_email_events_id', table_name='email_events')
    op.drop_table('email_events')

