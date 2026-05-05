"""add shared_items table for member-to-org item sharing

Revision ID: 007
Revises: 006
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS shared_items (
            id SERIAL PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(clerk_id) ON DELETE CASCADE,
            shared_by TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
            item_kind TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            note TEXT,
            shared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (org_id, item_kind, item_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_shared_items_org ON shared_items (org_id, shared_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_shared_items_org")
    op.execute("DROP TABLE IF EXISTS shared_items")
