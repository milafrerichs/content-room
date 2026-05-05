from typing import Optional

import psycopg2
import psycopg2.extras


def _connect(database_url: str):
    """Open a psycopg2 connection with RealDictCursor as the default cursor factory."""
    return psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)


def _fetchone(conn, sql: str, params=()) -> Optional[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def _fetchall(conn, sql: str, params=()) -> list:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def _execute(conn, sql: str, params=()) -> int:
    """Execute a write statement, commit, and return rowcount."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        cur.close()


def init_db(database_url: str):
    """Create schema (idempotent) and return an open connection."""
    conn = _connect(database_url)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            clerk_id TEXT PRIMARY KEY,
            email TEXT,
            display_name TEXT,
            image_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            clerk_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT,
            image_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS org_members (
            org_id TEXT NOT NULL REFERENCES organizations(clerk_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'org:member',
            joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (org_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS canonical_feeds (
            id SERIAL PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            feed_type TEXT NOT NULL,
            last_fetched_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS podcast_feeds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            auto_summarize INTEGER NOT NULL DEFAULT 0,
            owner_type TEXT NOT NULL DEFAULT 'user',
            owner_id TEXT,
            canonical_feed_id INTEGER REFERENCES canonical_feeds(id),
            is_shared BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS article_feeds (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            auto_summarize INTEGER NOT NULL DEFAULT 0,
            owner_type TEXT NOT NULL DEFAULT 'user',
            owner_id TEXT,
            canonical_feed_id INTEGER REFERENCES canonical_feeds(id),
            is_shared BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id SERIAL PRIMARY KEY,
            podcast_feed_id INTEGER NOT NULL REFERENCES podcast_feeds(id) ON DELETE CASCADE,
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
            canonical_feed_id INTEGER REFERENCES canonical_feeds(id),
            UNIQUE(podcast_feed_id, audio_url)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id SERIAL PRIMARY KEY,
            article_feed_id INTEGER NOT NULL REFERENCES article_feeds(id) ON DELETE CASCADE,
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
            canonical_feed_id INTEGER REFERENCES canonical_feeds(id),
            UNIQUE(article_feed_id, url)
        )
    """)

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    return conn
