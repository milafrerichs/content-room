import sqlite3

from content_agent import db


def test_episodes_table_has_started_at_column(tmp_db):
    conn = db.init_db(tmp_db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()]
    assert "started_at" in columns
    conn.close()


def test_articles_table_has_started_at_column(tmp_db):
    conn = db.init_db(tmp_db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()]
    assert "started_at" in columns
    conn.close()


def test_update_episode_status_sets_started_at_for_processing(tmp_db):
    conn = db.init_db(tmp_db)
    db.insert_episode(conn, "pod", "ep1", "http://a.mp3", "2025-01-01")
    row = conn.execute("SELECT id FROM episodes").fetchone()
    eid = row["id"]

    for status in ("downloading", "transcribing", "summarizing"):
        # Reset started_at first
        conn.execute("UPDATE episodes SET started_at = NULL WHERE id = ?", (eid,))
        conn.commit()

        db.update_episode_status(conn, eid, status)
        row = conn.execute("SELECT started_at FROM episodes WHERE id = ?", (eid,)).fetchone()
        assert row["started_at"] is not None, f"started_at should be set for status={status}"

    conn.close()


def test_update_episode_status_does_not_set_started_at_for_terminal(tmp_db):
    conn = db.init_db(tmp_db)
    db.insert_episode(conn, "pod", "ep1", "http://a.mp3", "2025-01-01")
    eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]

    for status in ("summarized", "failed"):
        db.update_episode_status(conn, eid, status)
        row = conn.execute("SELECT started_at FROM episodes WHERE id = ?", (eid,)).fetchone()
        assert row["started_at"] is None, f"started_at should not be set for status={status}"

    conn.close()


def test_update_article_status_sets_started_at_for_processing(tmp_db):
    conn = db.init_db(tmp_db)
    db.insert_article(conn, "feed", "art1", "http://a.html", "2025-01-01")
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]

    db.update_article_status(conn, aid, "summarizing")
    row = conn.execute("SELECT started_at FROM articles WHERE id = ?", (aid,)).fetchone()
    assert row["started_at"] is not None

    conn.close()


def test_update_article_status_does_not_set_started_at_for_terminal(tmp_db):
    conn = db.init_db(tmp_db)
    db.insert_article(conn, "feed", "art1", "http://a.html", "2025-01-01")
    aid = conn.execute("SELECT id FROM articles").fetchone()["id"]

    db.update_article_status(conn, aid, "summarized")
    row = conn.execute("SELECT started_at FROM articles WHERE id = ?", (aid,)).fetchone()
    assert row["started_at"] is None

    conn.close()


def test_init_db_sets_busy_timeout(tmp_db):
    conn = db.init_db(tmp_db)
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout >= 5000
    conn.close()


def test_started_at_migration_on_existing_db(tmp_db):
    """Verify migration adds started_at to a DB created without it."""
    # Create a DB without started_at (simulate old schema)
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""CREATE TABLE episodes (
        id INTEGER PRIMARY KEY, podcast_name TEXT, title TEXT,
        audio_url TEXT, published_date TEXT, status TEXT DEFAULT 'discovered',
        discovered_at TEXT DEFAULT (datetime('now')),
        UNIQUE(podcast_name, audio_url)
    )""")
    conn.execute("""CREATE TABLE articles (
        id INTEGER PRIMARY KEY, feed_name TEXT, title TEXT,
        url TEXT, published_date TEXT, status TEXT DEFAULT 'discovered',
        discovered_at TEXT DEFAULT (datetime('now')),
        UNIQUE(feed_name, url)
    )""")
    conn.commit()
    conn.close()

    # init_db should migrate
    conn = db.init_db(tmp_db)
    ep_cols = [r[1] for r in conn.execute("PRAGMA table_info(episodes)").fetchall()]
    art_cols = [r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()]
    assert "started_at" in ep_cols
    assert "started_at" in art_cols
    conn.close()
