"""add feed sharing, canonical feeds, and subscriptions

Revision ID: 005
Revises: 003
Create Date: 2026-05-05

"""
from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS canonical_feeds (
            id SERIAL PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            feed_type TEXT NOT NULL,
            last_fetched_at TIMESTAMPTZ
        )
    """)

    op.execute("ALTER TABLE podcast_feeds ADD COLUMN IF NOT EXISTS canonical_feed_id INTEGER REFERENCES canonical_feeds(id)")
    op.execute("ALTER TABLE article_feeds ADD COLUMN IF NOT EXISTS canonical_feed_id INTEGER REFERENCES canonical_feeds(id)")
    op.execute("ALTER TABLE episodes ADD COLUMN IF NOT EXISTS canonical_feed_id INTEGER REFERENCES canonical_feeds(id)")
    op.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS canonical_feed_id INTEGER REFERENCES canonical_feeds(id)")

    op.execute("ALTER TABLE podcast_feeds ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE article_feeds ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE")

    op.execute("""
        CREATE TABLE IF NOT EXISTS feed_subscriptions (
            id SERIAL PRIMARY KEY,
            subscriber_type TEXT NOT NULL,
            subscriber_id TEXT NOT NULL,
            feed_type TEXT NOT NULL,
            feed_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (subscriber_type, subscriber_id, feed_type, feed_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_feed_subs_subscriber ON feed_subscriptions (subscriber_type, subscriber_id)")

    # Backfill canonical_feeds from existing podcast_feeds (one row per unique URL)
    op.execute("""
        INSERT INTO canonical_feeds (url, feed_type)
        SELECT DISTINCT url, 'podcast'
        FROM podcast_feeds
        ON CONFLICT (url) DO NOTHING
    """)
    op.execute("""
        INSERT INTO canonical_feeds (url, feed_type)
        SELECT DISTINCT url, 'article'
        FROM article_feeds
        ON CONFLICT (url) DO NOTHING
    """)

    # Link existing feeds to their canonical rows
    op.execute("""
        UPDATE podcast_feeds pf
        SET canonical_feed_id = cf.id
        FROM canonical_feeds cf
        WHERE cf.url = pf.url AND canonical_feed_id IS NULL
    """)
    op.execute("""
        UPDATE article_feeds af
        SET canonical_feed_id = cf.id
        FROM canonical_feeds cf
        WHERE cf.url = af.url AND canonical_feed_id IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_feed_subs_subscriber")
    op.execute("DROP TABLE IF EXISTS feed_subscriptions")
    op.execute("ALTER TABLE article_feeds DROP COLUMN IF EXISTS is_shared")
    op.execute("ALTER TABLE podcast_feeds DROP COLUMN IF EXISTS is_shared")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS canonical_feed_id")
    op.execute("ALTER TABLE episodes DROP COLUMN IF EXISTS canonical_feed_id")
    op.execute("ALTER TABLE article_feeds DROP COLUMN IF EXISTS canonical_feed_id")
    op.execute("ALTER TABLE podcast_feeds DROP COLUMN IF EXISTS canonical_feed_id")
    op.execute("DROP TABLE IF EXISTS canonical_feeds")
