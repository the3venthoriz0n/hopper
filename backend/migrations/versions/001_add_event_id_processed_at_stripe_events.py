"""Add event_id and processed_at to stripe_events

Revision ID: 001
Revises: 
Create Date: 2025-01-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add event_id column as nullable first
    op.add_column('stripe_events', sa.Column('event_id', sa.String(length=255), nullable=True))
    
    # Copy data from stripe_event_id to event_id for existing rows
    op.execute("UPDATE stripe_events SET event_id = stripe_event_id WHERE event_id IS NULL")
    
    # Now make event_id non-nullable
    op.alter_column('stripe_events', 'event_id', nullable=False)
    
    # Add unique constraint and index to event_id
    op.create_unique_constraint('uq_stripe_events_event_id', 'stripe_events', ['event_id'])
    op.create_index('ix_stripe_events_event_id', 'stripe_events', ['event_id'])
    
    # Add processed_at column
    op.add_column('stripe_events', sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove processed_at column
    op.drop_column('stripe_events', 'processed_at')
    
    # Remove index and constraint from event_id
    op.drop_index('ix_stripe_events_event_id', table_name='stripe_events')
    op.drop_constraint('uq_stripe_events_event_id', 'stripe_events', type_='unique')
    
    # Remove event_id column
    op.drop_column('stripe_events', 'event_id')

