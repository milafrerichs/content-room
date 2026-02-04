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
