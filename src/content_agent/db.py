import json
import sqlite3
from pathlib import Path
from typing import Optional

from .models import ArticleFeed, PodcastFeed, TaskModelOverride


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
            one_sentence_summary TEXT,
            processed_at TEXT,
            started_at TEXT,
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
            one_sentence_summary TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            error_message TEXT,
            summary_path TEXT,
            discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT,
            started_at TEXT,
            read_at TEXT,
            UNIQUE(feed_name, url)
        );

        CREATE TABLE IF NOT EXISTS podcast_feeds (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url  TEXT NOT NULL,
            category TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS article_feeds (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            url  TEXT NOT NULL,
            category TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    _migrate_add_started_at(conn)
    _migrate_add_one_sentence_summary(conn)
    _migrate_add_feed_category(conn)
    _migrate_add_archived_at(conn)
    _migrate_add_settings_table(conn)
    _migrate_add_auto_summarize(conn)
    _migrate_add_read_later_at(conn)
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


def _migrate_add_started_at(conn: sqlite3.Connection) -> None:
    """Add started_at column to episodes and articles if it doesn't exist."""
    for table in ("episodes", "articles"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "started_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN started_at TEXT")
            conn.commit()


def _migrate_add_one_sentence_summary(conn: sqlite3.Connection) -> None:
    """Add one_sentence_summary column to episodes and articles if it doesn't exist."""
    for table in ("episodes", "articles"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "one_sentence_summary" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN one_sentence_summary TEXT")
    conn.commit()


def _migrate_add_feed_category(conn: sqlite3.Connection) -> None:
    """Add category column to podcast_feeds and article_feeds if it doesn't exist."""
    for table in ("podcast_feeds", "article_feeds"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "category" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN category TEXT")
    conn.commit()


def _migrate_add_archived_at(conn: sqlite3.Connection) -> None:
    """Add archived_at column to episodes and articles if it doesn't exist."""
    for table in ("episodes", "articles"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "archived_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN archived_at TEXT")
    conn.commit()


def _migrate_add_settings_table(conn: sqlite3.Connection) -> None:
    """Create settings table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _migrate_add_auto_summarize(conn: sqlite3.Connection) -> None:
    """Add auto_summarize column to feed tables if it doesn't exist."""
    for table in ("podcast_feeds", "article_feeds"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "auto_summarize" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN auto_summarize INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _migrate_add_read_later_at(conn: sqlite3.Connection) -> None:
    """Add read_later_at column to episodes and articles if it doesn't exist."""
    for table in ("episodes", "articles"):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "read_later_at" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN read_later_at TEXT")
    conn.commit()


# =============================================================================
# Settings CRUD (task model overrides)
# =============================================================================


def get_task_model_overrides(conn: sqlite3.Connection) -> dict[str, TaskModelOverride]:
    """Read all task model overrides from the settings table."""
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE 'task_model:%'"
    ).fetchall()
    overrides = {}
    for row in rows:
        task_name = row["key"].removeprefix("task_model:")
        overrides[task_name] = TaskModelOverride(**json.loads(row["value"]))
    return overrides


def set_task_model_override(
    conn: sqlite3.Connection, task_name: str, override: TaskModelOverride
) -> None:
    """Save a per-task model override to the settings table."""
    conn.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (f"task_model:{task_name}", override.model_dump_json()),
    )
    conn.commit()


def delete_task_model_override(conn: sqlite3.Connection, task_name: str) -> None:
    """Remove a per-task model override, reverting to the global default."""
    conn.execute("DELETE FROM settings WHERE key = ?", (f"task_model:{task_name}",))
    conn.commit()


PROCESSING_STATUSES = ("downloading", "transcribing", "summarizing")


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

    if status in PROCESSING_STATUSES:
        updates.append("started_at = datetime('now')")
    if status in ("summarized", "failed"):
        updates.append("processed_at = datetime('now')")

    params.append(episode_id)
    conn.execute(
        f"UPDATE episodes SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def update_episode_one_sentence(
    conn: sqlite3.Connection, episode_id: int, summary: str
) -> None:
    """Set the one-sentence summary for an episode."""
    conn.execute(
        "UPDATE episodes SET one_sentence_summary = ? WHERE id = ?",
        (summary, episode_id),
    )
    conn.commit()


def reset_episode_for_rerun(conn: sqlite3.Connection, episode_id: int, reset_to_status: str) -> None:
    conn.execute(
        "UPDATE episodes SET status=?, error_message=NULL, processed_at=NULL WHERE id=?",
        (reset_to_status, episode_id),
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

    if status in PROCESSING_STATUSES:
        updates.append("started_at = datetime('now')")
    if status in ("summarized", "failed"):
        updates.append("processed_at = datetime('now')")

    params.append(article_id)
    conn.execute(
        f"UPDATE articles SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()


def update_article_one_sentence(
    conn: sqlite3.Connection, article_id: int, summary: str
) -> None:
    """Set the one-sentence summary for an article."""
    conn.execute(
        "UPDATE articles SET one_sentence_summary = ? WHERE id = ?",
        (summary, article_id),
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


def archive_episode(conn: sqlite3.Connection, episode_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE episodes SET archived_at = datetime('now') WHERE id = ? AND archived_at IS NULL",
        (episode_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def unarchive_episode(conn: sqlite3.Connection, episode_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE episodes SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",
        (episode_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def archive_article(conn: sqlite3.Connection, article_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE articles SET archived_at = datetime('now') WHERE id = ? AND archived_at IS NULL",
        (article_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def unarchive_article(conn: sqlite3.Connection, article_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE articles SET archived_at = NULL WHERE id = ? AND archived_at IS NOT NULL",
        (article_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_episode_read_later(conn: sqlite3.Connection, episode_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE episodes SET read_later_at = datetime('now') WHERE id = ? AND read_later_at IS NULL",
        (episode_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def unmark_episode_read_later(conn: sqlite3.Connection, episode_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE episodes SET read_later_at = NULL WHERE id = ? AND read_later_at IS NOT NULL",
        (episode_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_article_read_later(conn: sqlite3.Connection, article_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE articles SET read_later_at = datetime('now') WHERE id = ? AND read_later_at IS NULL",
        (article_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def unmark_article_read_later(conn: sqlite3.Connection, article_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE articles SET read_later_at = NULL WHERE id = ? AND read_later_at IS NOT NULL",
        (article_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_episode(conn: sqlite3.Connection, episode_id: int) -> bool:
    cursor = conn.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
    conn.commit()
    return cursor.rowcount > 0


def delete_article(conn: sqlite3.Connection, article_id: int) -> bool:
    cursor = conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
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


# =============================================================================
# Web Dashboard Queries
# =============================================================================


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    """Return summary stats for the web dashboard."""
    status_rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM episodes GROUP BY status"
    ).fetchall()
    by_status = {row["status"]: row["count"] for row in status_rows}

    today_count = conn.execute(
        "SELECT COUNT(*) as count FROM episodes WHERE date(discovered_at) = date('now')"
    ).fetchone()["count"]

    last_run = conn.execute(
        "SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()

    return {
        "by_status": by_status,
        "today_count": today_count,
        "last_run": dict(last_run) if last_run else None,
        "total": sum(by_status.values()),
    }


def get_all_episodes(
    conn: sqlite3.Connection,
    podcast_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Fetch episodes with optional filters for the web dashboard."""
    where, params = _episode_filters(podcast_name, status, date_from, date_to, search)
    query = f"SELECT * FROM episodes{where} ORDER BY published_date DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return conn.execute(query, params).fetchall()


def get_episode_count(
    conn: sqlite3.Connection,
    podcast_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    """Return total count matching the same filters as get_all_episodes."""
    where, params = _episode_filters(podcast_name, status, date_from, date_to, search)
    return conn.execute(f"SELECT COUNT(*) as c FROM episodes{where}", params).fetchone()["c"]


def _episode_filters(
    podcast_name: Optional[str],
    status: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    search: Optional[str],
    include_archived: bool = False,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if podcast_name:
        clauses.append("podcast_name = ?")
        params.append(podcast_name)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if date_from:
        clauses.append("date(published_date) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(published_date) <= date(?)")
        params.append(date_to)
    if search:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_distinct_podcast_names(conn: sqlite3.Connection) -> list[str]:
    """Get all distinct podcast names for filter dropdowns."""
    rows = conn.execute(
        "SELECT DISTINCT podcast_name FROM episodes ORDER BY podcast_name"
    ).fetchall()
    return [row["podcast_name"] for row in rows]


def get_all_articles(
    conn: sqlite3.Connection,
    feed_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Fetch articles with optional filters for the web dashboard."""
    where, params = _article_filters(feed_name, status, date_from, date_to, search)
    query = f"SELECT * FROM articles{where} ORDER BY published_date DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return conn.execute(query, params).fetchall()


def get_article_count(
    conn: sqlite3.Connection,
    feed_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    """Return total count matching the same filters as get_all_articles."""
    where, params = _article_filters(feed_name, status, date_from, date_to, search)
    return conn.execute(f"SELECT COUNT(*) as c FROM articles{where}", params).fetchone()["c"]


def _article_filters(
    feed_name: Optional[str],
    status: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    search: Optional[str],
    include_archived: bool = False,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if feed_name:
        clauses.append("feed_name = ?")
        params.append(feed_name)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if date_from:
        clauses.append("date(published_date) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(published_date) <= date(?)")
        params.append(date_to)
    if search:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_distinct_feed_names(conn: sqlite3.Connection) -> list[str]:
    """Get all distinct article feed names for filter dropdowns."""
    rows = conn.execute(
        "SELECT DISTINCT feed_name FROM articles ORDER BY feed_name"
    ).fetchall()
    return [row["feed_name"] for row in rows]


def reset_article_for_rerun(conn: sqlite3.Connection, article_id: int) -> None:
    """Reset an article to 'discovered' status for re-summarization."""
    conn.execute(
        "UPDATE articles SET status='discovered', error_message=NULL, processed_at=NULL WHERE id=?",
        (article_id,),
    )
    conn.commit()


def get_unified_feed(
    conn: sqlite3.Connection,
    source: Optional[str] = None,
    search: Optional[str] = None,
    include_archived: bool = False,
    archived_only: bool = False,
    read_later_only: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Return a unified list of articles and episodes, newest first."""
    clauses_ep: list[str] = []
    clauses_art: list[str] = []
    params_ep: list = []
    params_art: list = []

    if archived_only:
        clauses_ep.append("e.archived_at IS NOT NULL")
        clauses_art.append("a.archived_at IS NOT NULL")
    elif not include_archived:
        clauses_ep.append("e.archived_at IS NULL")
        clauses_art.append("a.archived_at IS NULL")

    if read_later_only:
        clauses_ep.append("e.read_later_at IS NOT NULL")
        clauses_art.append("a.read_later_at IS NOT NULL")

    if source:
        clauses_ep.append("podcast_name = ?")
        params_ep.append(source)
        clauses_art.append("feed_name = ?")
        params_art.append(source)
    if search:
        clauses_ep.append("(title LIKE ? OR description LIKE ?)")
        params_ep.extend([f"%{search}%", f"%{search}%"])
        clauses_art.append("(title LIKE ? OR description LIKE ?)")
        params_art.extend([f"%{search}%", f"%{search}%"])

    where_ep = (" AND " + " AND ".join(clauses_ep)) if clauses_ep else ""
    where_art = (" AND " + " AND ".join(clauses_art)) if clauses_art else ""

    query = f"""
        SELECT e.id, 'episode' as kind, e.podcast_name as source, e.title,
               e.published_date, e.status, e.one_sentence_summary, e.read_at,
               COALESCE(pf.category, '') as category, e.archived_at,
               e.read_later_at, e.description
        FROM episodes e
        LEFT JOIN podcast_feeds pf ON pf.name = e.podcast_name
        WHERE 1=1{where_ep.replace('podcast_name', 'e.podcast_name').replace('title', 'e.title').replace('description', 'e.description')}
        UNION ALL
        SELECT a.id, 'article' as kind, a.feed_name as source, a.title,
               a.published_date, a.status, a.one_sentence_summary, a.read_at,
               COALESCE(af.category, '') as category, a.archived_at,
               a.read_later_at, a.description
        FROM articles a
        LEFT JOIN article_feeds af ON af.name = a.feed_name
        WHERE 1=1{where_art.replace('feed_name', 'a.feed_name').replace('title', 'a.title').replace('description', 'a.description')}
        ORDER BY published_date DESC
        LIMIT ?
    """
    params = params_ep + params_art + [limit]
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_unified_feed_item(conn: sqlite3.Connection, kind: str, item_id: int) -> Optional[dict]:
    """Fetch a single unified feed item by kind and id."""
    if kind == "episode":
        row = conn.execute(
            """SELECT e.id, 'episode' as kind, e.podcast_name as source, e.title,
                      e.published_date, e.status, e.one_sentence_summary, e.read_at,
                      COALESCE(pf.category, '') as category, e.archived_at,
                      e.read_later_at, e.description
               FROM episodes e
               LEFT JOIN podcast_feeds pf ON pf.name = e.podcast_name
               WHERE e.id = ?""",
            (item_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT a.id, 'article' as kind, a.feed_name as source, a.title,
                      a.published_date, a.status, a.one_sentence_summary, a.read_at,
                      COALESCE(af.category, '') as category, a.archived_at,
                      a.read_later_at, a.description
               FROM articles a
               LEFT JOIN article_feeds af ON af.name = a.feed_name
               WHERE a.id = ?""",
            (item_id,),
        ).fetchone()
    return dict(row) if row else None


def get_all_feed_sources(conn: sqlite3.Connection) -> list[str]:
    """Get all distinct source names (podcast + article feed names) for filter dropdown."""
    rows = conn.execute("""
        SELECT DISTINCT podcast_name as name FROM episodes
        UNION
        SELECT DISTINCT feed_name as name FROM articles
        ORDER BY name
    """).fetchall()
    return [row["name"] for row in rows]


def get_all_feed_categories(conn: sqlite3.Connection) -> list[str]:
    """Get all distinct non-empty categories across podcast and article feeds."""
    rows = conn.execute("""
        SELECT DISTINCT category FROM podcast_feeds WHERE category IS NOT NULL AND category != ''
        UNION
        SELECT DISTINCT category FROM article_feeds WHERE category IS NOT NULL AND category != ''
        ORDER BY category
    """).fetchall()
    return [row["category"] for row in rows]


def get_all_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Get all runs ordered by most recent first."""
    return conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()


# =============================================================================
# Feed Management Functions
# =============================================================================


def get_podcast_feeds(conn: sqlite3.Connection) -> list[PodcastFeed]:
    """Return all podcast feeds as PodcastFeed model instances."""
    rows = conn.execute("SELECT name, url, category, auto_summarize FROM podcast_feeds ORDER BY name").fetchall()
    return [PodcastFeed(name=row["name"], url=row["url"], category=row["category"], auto_summarize=bool(row["auto_summarize"])) for row in rows]


def upsert_podcast_feed(
    conn: sqlite3.Connection, name: str, url: str, category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    if category is not None and auto_summarize is not None:
        conn.execute(
            """INSERT INTO podcast_feeds (name, url, category, auto_summarize) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, category=excluded.category, auto_summarize=excluded.auto_summarize""",
            (name, url, category, int(auto_summarize)),
        )
    elif category is not None:
        conn.execute(
            """INSERT INTO podcast_feeds (name, url, category) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, category=excluded.category""",
            (name, url, category),
        )
    elif auto_summarize is not None:
        conn.execute(
            """INSERT INTO podcast_feeds (name, url, auto_summarize) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, auto_summarize=excluded.auto_summarize""",
            (name, url, int(auto_summarize)),
        )
    else:
        conn.execute(
            """INSERT INTO podcast_feeds (name, url) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url""",
            (name, url),
        )


def update_podcast_feed_category(conn: sqlite3.Connection, name: str, category: str) -> None:
    conn.execute("UPDATE podcast_feeds SET category = ? WHERE name = ?", (category, name))
    conn.commit()


def update_podcast_feed_auto_summarize(conn: sqlite3.Connection, name: str, auto_summarize: bool) -> None:
    conn.execute("UPDATE podcast_feeds SET auto_summarize = ? WHERE name = ?", (int(auto_summarize), name))
    conn.commit()


def delete_podcast_feed(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM podcast_feeds WHERE name = ?", (name,))


def get_article_feeds(conn: sqlite3.Connection) -> list[ArticleFeed]:
    """Return all article feeds as ArticleFeed model instances."""
    rows = conn.execute("SELECT name, url, category, auto_summarize FROM article_feeds ORDER BY name").fetchall()
    return [ArticleFeed(name=row["name"], url=row["url"], category=row["category"], auto_summarize=bool(row["auto_summarize"])) for row in rows]


def upsert_article_feed(
    conn: sqlite3.Connection, name: str, url: str, category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    if category is not None and auto_summarize is not None:
        conn.execute(
            """INSERT INTO article_feeds (name, url, category, auto_summarize) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, category=excluded.category, auto_summarize=excluded.auto_summarize""",
            (name, url, category, int(auto_summarize)),
        )
    elif category is not None:
        conn.execute(
            """INSERT INTO article_feeds (name, url, category) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, category=excluded.category""",
            (name, url, category),
        )
    elif auto_summarize is not None:
        conn.execute(
            """INSERT INTO article_feeds (name, url, auto_summarize) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url, auto_summarize=excluded.auto_summarize""",
            (name, url, int(auto_summarize)),
        )
    else:
        conn.execute(
            """INSERT INTO article_feeds (name, url) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET url=excluded.url""",
            (name, url),
        )


def update_article_feed_category(conn: sqlite3.Connection, name: str, category: str) -> None:
    conn.execute("UPDATE article_feeds SET category = ? WHERE name = ?", (category, name))
    conn.commit()


def update_article_feed_auto_summarize(conn: sqlite3.Connection, name: str, auto_summarize: bool) -> None:
    conn.execute("UPDATE article_feeds SET auto_summarize = ? WHERE name = ?", (int(auto_summarize), name))
    conn.commit()


def delete_article_feed(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM article_feeds WHERE name = ?", (name,))


def get_podcast_feed_by_name(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    """Get a single podcast feed by name."""
    return conn.execute(
        "SELECT * FROM podcast_feeds WHERE name = ?", (name,)
    ).fetchone()


def get_episodes_by_podcast(conn: sqlite3.Connection, podcast_name: str) -> dict[str, sqlite3.Row]:
    """Return all episodes for a podcast, keyed by audio_url for fast lookup."""
    rows = conn.execute(
        "SELECT * FROM episodes WHERE podcast_name = ?", (podcast_name,)
    ).fetchall()
    return {row["audio_url"]: row for row in rows}


def get_podcast_feeds_with_stats(conn: sqlite3.Connection) -> list[dict]:
    """Return podcast feeds with last item date and item count."""
    rows = conn.execute("""
        SELECT pf.name, pf.url, pf.category, pf.auto_summarize,
               MAX(e.published_date) as last_item_date,
               COUNT(e.id) as item_count
        FROM podcast_feeds pf
        LEFT JOIN episodes e ON pf.name = e.podcast_name
        GROUP BY pf.id
        ORDER BY COALESCE(pf.category, 'zzz'), pf.name
    """).fetchall()
    return [dict(row) for row in rows]


def get_article_feeds_with_stats(conn: sqlite3.Connection) -> list[dict]:
    """Return article feeds with last item date and item count."""
    rows = conn.execute("""
        SELECT af.name, af.url, af.category, af.auto_summarize,
               MAX(a.published_date) as last_item_date,
               COUNT(a.id) as item_count
        FROM article_feeds af
        LEFT JOIN articles a ON af.name = a.feed_name
        GROUP BY af.id
        ORDER BY COALESCE(af.category, 'zzz'), af.name
    """).fetchall()
    return [dict(row) for row in rows]
