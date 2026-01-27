"""Add tokens_required to videos

Revision ID: 003
Revises: 002
Create Date: 2025-12-26 16:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if column already exists (in case migration was partially applied)
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('videos')]
    
    # Add tokens_required column as nullable (for backward compatibility with existing videos) if it doesn't exist
    if 'tokens_required' not in existing_columns:
        op.add_column('videos', sa.Column('tokens_required', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Remove tokens_required column
    op.drop_column('videos', 'tokens_required')

