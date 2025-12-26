"""Add preserved_plan_type to subscriptions

Revision ID: 002
Revises: 001
Create Date: 2025-01-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add preserved_plan_type column as nullable
    op.add_column('subscriptions', sa.Column('preserved_plan_type', sa.String(length=50), nullable=True))


def downgrade() -> None:
    # Remove preserved_plan_type column
    op.drop_column('subscriptions', 'preserved_plan_type')

