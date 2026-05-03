"""add users table and feed ownership

Revision ID: 002
Revises: 001
Create Date: 2026-05-03

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            clerk_id TEXT PRIMARY KEY,
            email TEXT,
            display_name TEXT,
            image_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # owner_id is nullable so the migration can run before the data migration script assigns
    # real Clerk IDs. Run scripts/migrate_to_user.py after upgrading on an existing DB.
    op.execute("ALTER TABLE podcast_feeds ADD COLUMN IF NOT EXISTS owner_type TEXT NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE podcast_feeds ADD COLUMN IF NOT EXISTS owner_id TEXT")
    op.execute("ALTER TABLE article_feeds ADD COLUMN IF NOT EXISTS owner_type TEXT NOT NULL DEFAULT 'user'")
    op.execute("ALTER TABLE article_feeds ADD COLUMN IF NOT EXISTS owner_id TEXT")

    op.execute("ALTER TABLE podcast_feeds DROP CONSTRAINT IF EXISTS podcast_feeds_name_key")
    op.execute("ALTER TABLE article_feeds  DROP CONSTRAINT IF EXISTS article_feeds_name_key")

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS podcast_feeds_owner_name_key
            ON podcast_feeds (owner_type, owner_id, name)
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS article_feeds_owner_name_key
            ON article_feeds (owner_type, owner_id, name)
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_podcast_feeds_owner ON podcast_feeds (owner_type, owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_article_feeds_owner ON article_feeds (owner_type, owner_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_article_feeds_owner")
    op.execute("DROP INDEX IF EXISTS idx_podcast_feeds_owner")
    op.execute("DROP INDEX IF EXISTS article_feeds_owner_name_key")
    op.execute("DROP INDEX IF EXISTS podcast_feeds_owner_name_key")

    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS podcast_feeds_name_key ON podcast_feeds (name)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS article_feeds_name_key ON article_feeds (name)")

    op.execute("ALTER TABLE article_feeds DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE article_feeds DROP COLUMN IF EXISTS owner_type")
    op.execute("ALTER TABLE podcast_feeds DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE podcast_feeds DROP COLUMN IF EXISTS owner_type")

    op.execute("DROP TABLE IF EXISTS users")
