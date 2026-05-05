"""add organizations, org_members tables and refactor episode/article FK

Revision ID: 003
Revises: 002
Create Date: 2026-05-04

"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            clerk_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT,
            image_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS org_members (
            org_id TEXT NOT NULL REFERENCES organizations(clerk_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'org:member',
            joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (org_id, user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members (user_id)")

    # --- FK refactor: episodes.podcast_name -> episodes.podcast_feed_id ---
    op.execute("ALTER TABLE episodes ADD COLUMN podcast_feed_id INTEGER")
    op.execute("""
        UPDATE episodes SET podcast_feed_id = pf.id
        FROM podcast_feeds pf WHERE pf.name = episodes.podcast_name
    """)
    op.execute("DELETE FROM episodes WHERE podcast_feed_id IS NULL")
    op.execute("ALTER TABLE episodes ALTER COLUMN podcast_feed_id SET NOT NULL")
    op.execute("""
        ALTER TABLE episodes ADD CONSTRAINT fk_episodes_podcast_feed
        FOREIGN KEY (podcast_feed_id) REFERENCES podcast_feeds(id) ON DELETE CASCADE
    """)
    op.execute("ALTER TABLE episodes DROP CONSTRAINT IF EXISTS episodes_podcast_name_audio_url_key")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS episodes_feed_audio_url_key ON episodes (podcast_feed_id, audio_url)")
    op.execute("ALTER TABLE episodes DROP COLUMN podcast_name")
    op.execute("CREATE INDEX IF NOT EXISTS idx_episodes_podcast_feed_id ON episodes (podcast_feed_id)")

    # --- FK refactor: articles.feed_name -> articles.article_feed_id ---
    op.execute("ALTER TABLE articles ADD COLUMN article_feed_id INTEGER")
    op.execute("""
        UPDATE articles SET article_feed_id = af.id
        FROM article_feeds af WHERE af.name = articles.feed_name
    """)
    op.execute("DELETE FROM articles WHERE article_feed_id IS NULL")
    op.execute("ALTER TABLE articles ALTER COLUMN article_feed_id SET NOT NULL")
    op.execute("""
        ALTER TABLE articles ADD CONSTRAINT fk_articles_article_feed
        FOREIGN KEY (article_feed_id) REFERENCES article_feeds(id) ON DELETE CASCADE
    """)
    op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS articles_feed_name_url_key")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS articles_feed_url_key ON articles (article_feed_id, url)")
    op.execute("ALTER TABLE articles DROP COLUMN feed_name")
    op.execute("CREATE INDEX IF NOT EXISTS idx_articles_article_feed_id ON articles (article_feed_id)")


def downgrade() -> None:
    # Restore articles.feed_name
    op.execute("ALTER TABLE articles ADD COLUMN feed_name TEXT")
    op.execute("""
        UPDATE articles SET feed_name = af.name
        FROM article_feeds af WHERE af.id = articles.article_feed_id
    """)
    op.execute("ALTER TABLE articles ALTER COLUMN feed_name SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS idx_articles_article_feed_id")
    op.execute("DROP INDEX IF EXISTS articles_feed_url_key")
    op.execute("ALTER TABLE articles DROP CONSTRAINT IF EXISTS fk_articles_article_feed")
    op.execute("ALTER TABLE articles DROP COLUMN article_feed_id")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS articles_feed_name_url_key ON articles (feed_name, url)")

    # Restore episodes.podcast_name
    op.execute("ALTER TABLE episodes ADD COLUMN podcast_name TEXT")
    op.execute("""
        UPDATE episodes SET podcast_name = pf.name
        FROM podcast_feeds pf WHERE pf.id = episodes.podcast_feed_id
    """)
    op.execute("ALTER TABLE episodes ALTER COLUMN podcast_name SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS idx_episodes_podcast_feed_id")
    op.execute("DROP INDEX IF EXISTS episodes_feed_audio_url_key")
    op.execute("ALTER TABLE episodes DROP CONSTRAINT IF EXISTS fk_episodes_podcast_feed")
    op.execute("ALTER TABLE episodes DROP COLUMN podcast_feed_id")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS episodes_podcast_name_audio_url_key ON episodes (podcast_name, audio_url)")

    # Drop org tables
    op.execute("DROP INDEX IF EXISTS idx_org_members_user")
    op.execute("DROP TABLE IF EXISTS org_members")
    op.execute("DROP TABLE IF EXISTS organizations")
