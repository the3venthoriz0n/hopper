"""Create wordbank_words table

Revision ID: 005
Revises: 004
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
import json


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if table already exists
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    if 'wordbank_words' not in existing_tables:
        op.create_table(
            'wordbank_words',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('word', sa.String(length=255), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
        )
        op.create_index('ix_wordbank_words_id', 'wordbank_words', ['id'])
        op.create_index('ix_wordbank_words_user_id', 'wordbank_words', ['user_id'])
        op.create_index('ix_wordbank_words_user_word', 'wordbank_words', ['user_id', 'word'])
        op.create_unique_constraint('uq_wordbank_words_user_word', 'wordbank_words', ['user_id', 'word'])
    else:
        # Table exists, but check if indexes/constraints exist and create them if missing
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('wordbank_words')]
        existing_constraints = [con['name'] for con in inspector.get_unique_constraints('wordbank_words')]
        
        if 'ix_wordbank_words_id' not in existing_indexes:
            op.create_index('ix_wordbank_words_id', 'wordbank_words', ['id'])
        if 'ix_wordbank_words_user_id' not in existing_indexes:
            op.create_index('ix_wordbank_words_user_id', 'wordbank_words', ['user_id'])
        if 'ix_wordbank_words_user_word' not in existing_indexes:
            op.create_index('ix_wordbank_words_user_word', 'wordbank_words', ['user_id', 'word'])
        if 'uq_wordbank_words_user_word' not in existing_constraints:
            op.create_unique_constraint('uq_wordbank_words_user_word', 'wordbank_words', ['user_id', 'word'])
    
    # Migrate existing wordbank data from settings table
    # Query all settings with category='global' and key='wordbank'
    result = conn.execute(text("""
        SELECT user_id, value 
        FROM settings 
        WHERE category = 'global' AND key = 'wordbank'
    """))
    
    migrated_count = 0
    for row in result:
        user_id = row[0]
        value_str = row[1]
        
        if not value_str:
            continue
        
        try:
            # Parse JSON array
            wordbank = json.loads(value_str)
            if not isinstance(wordbank, list):
                continue
            
            # Insert each word (handle duplicates gracefully with ON CONFLICT)
            for word in wordbank:
                if not word or not isinstance(word, str):
                    continue
                
                # Normalize word (strip and capitalize)
                normalized_word = word.strip().capitalize()
                if not normalized_word:
                    continue
                
                # Use INSERT ... ON CONFLICT DO NOTHING to handle duplicates
                try:
                    conn.execute(text("""
                        INSERT INTO wordbank_words (user_id, word, created_at)
                        VALUES (:user_id, :word, NOW())
                        ON CONFLICT (user_id, word) DO NOTHING
                    """), {"user_id": user_id, "word": normalized_word})
                    migrated_count += 1
                except Exception as e:
                    # If word already exists (shouldn't happen with ON CONFLICT, but handle gracefully)
                    pass
            
        except (json.JSONDecodeError, TypeError):
            # Skip invalid JSON
            continue
    
    conn.commit()
    
    # Note: We keep the wordbank in settings table for backward compatibility
    # It will be ignored once the new table has data


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()
    
    if 'wordbank_words' in existing_tables:
        # Migrate data back to settings table before dropping
        result = conn.execute(text("""
            SELECT user_id, array_agg(word ORDER BY created_at) as words
            FROM wordbank_words
            GROUP BY user_id
        """))
        
        for row in result:
            user_id = row[0]
            words = row[1] if row[1] else []
            
            # Update or insert wordbank in settings table
            wordbank_json = json.dumps(words)
            conn.execute(text("""
                INSERT INTO settings (user_id, category, key, value)
                VALUES (:user_id, 'global', 'wordbank', :value)
                ON CONFLICT (user_id, category, key) 
                DO UPDATE SET value = :value
            """), {"user_id": user_id, "value": wordbank_json})
        
        conn.commit()
        
        # Drop constraints and indexes
        existing_constraints = [con['name'] for con in inspector.get_unique_constraints('wordbank_words')]
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('wordbank_words')]
        
        if 'uq_wordbank_words_user_word' in existing_constraints:
            op.drop_constraint('uq_wordbank_words_user_word', 'wordbank_words', type_='unique')
        if 'ix_wordbank_words_user_word' in existing_indexes:
            op.drop_index('ix_wordbank_words_user_word', table_name='wordbank_words')
        if 'ix_wordbank_words_user_id' in existing_indexes:
            op.drop_index('ix_wordbank_words_user_id', table_name='wordbank_words')
        if 'ix_wordbank_words_id' in existing_indexes:
            op.drop_index('ix_wordbank_words_id', table_name='wordbank_words')
        
        op.drop_table('wordbank_words')

