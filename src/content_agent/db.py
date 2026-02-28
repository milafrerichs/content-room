import sqlite3
from pathlib import Path
from typing import Optional


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT,
            read_at TEXT,
            UNIQUE(podcast_name, audio_url)
        );

        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_date TEXT NOT NULL,
            author TEXT,
            content TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            error_message TEXT,
            summary_path TEXT,
            discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT,
            read_at TEXT,
            UNIQUE(feed_name, url)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            episodes_discovered INTEGER DEFAULT 0,
            episodes_processed INTEGER DEFAULT 0,
            episodes_failed INTEGER DEFAULT 0,
            articles_discovered INTEGER DEFAULT 0,
            articles_processed INTEGER DEFAULT 0,
            articles_failed INTEGER DEFAULT 0
        );
    """)
    _migrate_add_read_at(conn)
    _migrate_add_articles_to_runs(conn)
    return conn


def _migrate_add_read_at(conn: sqlite3.Connection) -> None:
    """Add read_at column if it doesn't exist (for existing databases)."""
    cursor = conn.execute("PRAGMA table_info(episodes)")
    columns = [row[1] for row in cursor.fetchall()]
    if "read_at" not in columns:
        conn.execute("ALTER TABLE episodes ADD COLUMN read_at TEXT")
        conn.commit()


def _migrate_add_articles_to_runs(conn: sqlite3.Connection) -> None:
    """Add article tracking columns to runs table if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(runs)")
    columns = [row[1] for row in cursor.fetchall()]
    if "articles_discovered" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN articles_discovered INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE runs ADD COLUMN articles_processed INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE runs ADD COLUMN articles_failed INTEGER DEFAULT 0")
        conn.commit()


def insert_episode(
    conn: sqlite3.Connection,
    podcast_name: str,
    title: str,
    audio_url: str,
    published_date: str,
    duration: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Insert a new episode. Returns True if inserted, False if already exists."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO episodes
               (podcast_name, title, audio_url, published_date, duration, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (podcast_name, title, audio_url, published_date, duration, description),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error:
        return False


def update_episode_status(
    conn: sqlite3.Connection,
    episode_id: int,
    status: str,
    error_message: Optional[str] = None,
    local_audio_path: Optional[str] = None,
    transcript_path: Optional[str] = None,
    summary_path: Optional[str] = None,
) -> None:
    updates = ["status = ?"]
    params: list = [status]

    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)
    if local_audio_path is not None:
        updates.append("local_audio_path = ?")
        params.append(local_audio_path)
    if transcript_path is not None:
        updates.append("transcript_path = ?")
        params.append(transcript_path)
    if summary_path is not None:
        updates.append("summary_path = ?")
        params.append(summary_path)

    if status in ("summarized", "failed"):
        updates.append("processed_at = datetime('now')")

    params.append(episode_id)
    conn.execute(
        f"UPDATE episodes SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def get_pending_episodes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get episodes that haven't been fully processed yet."""
    return conn.execute(
        "SELECT * FROM episodes WHERE status IN ('discovered', 'downloaded', 'transcribed') ORDER BY id"
    ).fetchall()


def get_unread_episodes(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Get summarized episodes that haven't been marked as read."""
    return conn.execute(
        """SELECT id, podcast_name, title, published_date, summary_path
           FROM episodes
           WHERE status = 'summarized' AND read_at IS NULL
           ORDER BY published_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def get_episode_by_id(conn: sqlite3.Connection, episode_id: int) -> Optional[sqlite3.Row]:
    """Get a single episode by ID."""
    return conn.execute(
        "SELECT * FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()


def mark_episode_read(conn: sqlite3.Connection, episode_id: int) -> bool:
    """Mark an episode as read. Returns True if the episode was found and updated."""
    cursor = conn.execute(
        "UPDATE episodes SET read_at = datetime('now') WHERE id = ?",
        (episode_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_podcast_stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get podcast names with unread/total episode counts."""
    return conn.execute(
        """SELECT
               podcast_name,
               COUNT(*) as total_episodes,
               SUM(CASE WHEN status = 'summarized' AND read_at IS NULL THEN 1 ELSE 0 END) as unread_count
           FROM episodes
           GROUP BY podcast_name
           ORDER BY podcast_name"""
    ).fetchall()


def search_episodes(
    conn: sqlite3.Connection, query: str, search_in: str = "summaries"
) -> list[sqlite3.Row]:
    """Search episodes by title/description. Returns matching episodes.

    Note: Full-text search of summary/transcript content is done at file level,
    this just returns candidate episodes based on metadata.
    """
    search_pattern = f"%{query}%"
    return conn.execute(
        """SELECT id, podcast_name, title, published_date, summary_path, transcript_path
           FROM episodes
           WHERE status = 'summarized'
             AND (title LIKE ? OR description LIKE ?)
           ORDER BY published_date DESC
           LIMIT 50""",
        (search_pattern, search_pattern),
    ).fetchall()


def start_run(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("INSERT INTO runs DEFAULT VALUES")
    conn.commit()
    return cursor.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    episodes_discovered: int,
    episodes_processed: int,
    episodes_failed: int,
    articles_discovered: int = 0,
    articles_processed: int = 0,
    articles_failed: int = 0,
) -> None:
    conn.execute(
        """UPDATE runs SET
           finished_at = datetime('now'),
           episodes_discovered = ?,
           episodes_processed = ?,
           episodes_failed = ?,
           articles_discovered = ?,
           articles_processed = ?,
           articles_failed = ?
           WHERE id = ?""",
        (
            episodes_discovered,
            episodes_processed,
            episodes_failed,
            articles_discovered,
            articles_processed,
            articles_failed,
            run_id,
        ),
    )
    conn.commit()


# =============================================================================
# Article CRUD Functions
# =============================================================================


def insert_article(
    conn: sqlite3.Connection,
    feed_name: str,
    title: str,
    url: str,
    published_date: str,
    author: Optional[str] = None,
    content: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Insert a new article. Returns True if inserted, False if already exists."""
    try:
        conn.execute(
            """INSERT OR IGNORE INTO articles
               (feed_name, title, url, published_date, author, content, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (feed_name, title, url, published_date, author, content, description),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error:
        return False


def update_article_status(
    conn: sqlite3.Connection,
    article_id: int,
    status: str,
    error_message: Optional[str] = None,
    summary_path: Optional[str] = None,
) -> None:
    updates = ["status = ?"]
    params: list = [status]

    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)
    if summary_path is not None:
        updates.append("summary_path = ?")
        params.append(summary_path)

    if status in ("summarized", "failed"):
        updates.append("processed_at = datetime('now')")

    params.append(article_id)
    conn.execute(
        f"UPDATE articles SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def get_pending_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get articles that haven't been summarized yet."""
    return conn.execute(
        "SELECT * FROM articles WHERE status = 'discovered' ORDER BY id"
    ).fetchall()


def get_unread_articles(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Get summarized articles that haven't been marked as read."""
    return conn.execute(
        """SELECT id, feed_name, title, url, published_date, author, summary_path
           FROM articles
           WHERE status = 'summarized' AND read_at IS NULL
           ORDER BY published_date DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def get_article_by_id(conn: sqlite3.Connection, article_id: int) -> Optional[sqlite3.Row]:
    """Get a single article by ID."""
    return conn.execute(
        "SELECT * FROM articles WHERE id = ?", (article_id,)
    ).fetchone()


def mark_article_read(conn: sqlite3.Connection, article_id: int) -> bool:
    """Mark an article as read. Returns True if the article was found and updated."""
    cursor = conn.execute(
        "UPDATE articles SET read_at = datetime('now') WHERE id = ?",
        (article_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_feed_stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get article feed names with unread/total article counts."""
    return conn.execute(
        """SELECT
               feed_name,
               COUNT(*) as total_articles,
               SUM(CASE WHEN status = 'summarized' AND read_at IS NULL THEN 1 ELSE 0 END) as unread_count
           FROM articles
           GROUP BY feed_name
           ORDER BY feed_name"""
    ).fetchall()


def search_articles(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search articles by title, description, or content."""
    search_pattern = f"%{query}%"
    return conn.execute(
        """SELECT id, feed_name, title, url, published_date, author, summary_path, content
           FROM articles
           WHERE status = 'summarized'
             AND (title LIKE ? OR description LIKE ? OR content LIKE ?)
           ORDER BY published_date DESC
           LIMIT 50""",
        (search_pattern, search_pattern, search_pattern),
    ).fetchall()
