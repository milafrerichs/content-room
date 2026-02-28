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
            UNIQUE(podcast_name, audio_url)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            episodes_discovered INTEGER DEFAULT 0,
            episodes_processed INTEGER DEFAULT 0,
            episodes_failed INTEGER DEFAULT 0
        );
    """)
    # Add read_at column if it doesn't exist (backwards-compatible migration)
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN read_at TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    return conn


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
) -> None:
    conn.execute(
        """UPDATE runs SET
           finished_at = datetime('now'),
           episodes_discovered = ?,
           episodes_processed = ?,
           episodes_failed = ?
           WHERE id = ?""",
        (episodes_discovered, episodes_processed, episodes_failed, run_id),
    )
    conn.commit()


# --- Dashboard / Web queries ---


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    """Return summary stats for the dashboard."""
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
    """Fetch episodes with optional filters."""
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
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
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


def get_episode_by_id(conn: sqlite3.Connection, episode_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()


def get_distinct_podcast_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT podcast_name FROM episodes ORDER BY podcast_name"
    ).fetchall()
    return [row["podcast_name"] for row in rows]


def mark_episode_read(conn: sqlite3.Connection, episode_id: int) -> None:
    conn.execute(
        "UPDATE episodes SET read_at = datetime('now') WHERE id = ?", (episode_id,)
    )
    conn.commit()


def get_all_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
