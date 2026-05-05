"""add per-user item read state table

Revision ID: 006
Revises: 005
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_item_state (
            user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
            item_kind TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            read_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            read_later_at TIMESTAMPTZ,
            PRIMARY KEY (user_id, item_kind, item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_item_state ON user_item_state (user_id, item_kind)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_item_state")
    op.execute("DROP TABLE IF EXISTS user_item_state")
