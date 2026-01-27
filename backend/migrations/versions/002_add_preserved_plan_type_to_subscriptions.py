"""Add preserved_plan_type to subscriptions

Revision ID: 002
Revises: 001
Create Date: 2025-01-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if column already exists (in case migration was partially applied)
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('subscriptions')]
    
    # Add preserved_plan_type column as nullable if it doesn't exist
    if 'preserved_plan_type' not in existing_columns:
        op.add_column('subscriptions', sa.Column('preserved_plan_type', sa.String(length=50), nullable=True))


def downgrade() -> None:
    # Remove preserved_plan_type column
    op.drop_column('subscriptions', 'preserved_plan_type')

