"""baseline schema

Revision ID: 001
Revises:
Create Date: 2026-05-02

"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id SERIAL PRIMARY KEY,
            podcast_name TEXT NOT NULL,
            title TEXT NOT NULL,
            audio_url TEXT NOT NULL,
            published_date TEXT NOT NULL,
            duration TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            error_message TEXT,
            local_audio_path TEXT,
            transcript_path TEXT,
            summary_path TEXT,
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            one_sentence_summary TEXT,
            processed_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            read_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            read_later_at TIMESTAMPTZ,
            UNIQUE(podcast_name, audio_url)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id SERIAL PRIMARY KEY,
            feed_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_date TEXT NOT NULL,
            author TEXT,
            content TEXT,
            description TEXT,
            one_sentence_summary TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            error_message TEXT,
            summary_path TEXT,
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            read_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            read_later_at TIMESTAMPTZ,
            UNIQUE(feed_name, url)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS podcast_feeds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            auto_summarize INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS article_feeds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            url TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            auto_summarize INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id SERIAL PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            episodes_discovered INTEGER DEFAULT 0,
            episodes_processed INTEGER DEFAULT 0,
            episodes_failed INTEGER DEFAULT 0,
            articles_discovered INTEGER DEFAULT 0,
            articles_processed INTEGER DEFAULT 0,
            articles_failed INTEGER DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS settings")
    op.execute("DROP TABLE IF EXISTS runs")
    op.execute("DROP TABLE IF EXISTS article_feeds")
    op.execute("DROP TABLE IF EXISTS podcast_feeds")
    op.execute("DROP TABLE IF EXISTS articles")
    op.execute("DROP TABLE IF EXISTS episodes")
