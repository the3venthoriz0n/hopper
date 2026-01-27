"""Create system_settings table

Revision ID: 007
Revises: 006
Create Date: 2025-01-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if table already exists
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    if 'system_settings' not in existing_tables:
        op.create_table(
            'system_settings',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_system_settings_id', 'system_settings', ['id'])
        op.create_index('ix_system_settings_key', 'system_settings', ['key'])
        op.create_unique_constraint('uq_system_settings_key', 'system_settings', ['key'])


def downgrade() -> None:
    # Drop table if it exists
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    if 'system_settings' in existing_tables:
        op.drop_index('ix_system_settings_key', table_name='system_settings')
        op.drop_index('ix_system_settings_id', table_name='system_settings')
        op.drop_table('system_settings')
