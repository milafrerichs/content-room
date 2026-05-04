from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone
from content_agent.web.auth import Owner

PROCESSING_STATUSES = ("downloading", "transcribing", "summarizing")


def insert(
    conn,
    podcast_name: str,
    title: str,
    audio_url: str,
    published_date: str,
    duration: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Insert a new episode. Returns True if inserted, False if already exists."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO episodes
           (podcast_name, title, audio_url, published_date, duration, description)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (podcast_name, title, audio_url, published_date, duration, description),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    cur.close()
    return inserted


def update_status(
    conn,
    episode_id: int,
    status: str,
    error_message: Optional[str] = None,
    local_audio_path: Optional[str] = None,
    transcript_path: Optional[str] = None,
    summary_path: Optional[str] = None,
) -> None:
    updates = ["status = %s"]
    params: list = [status]

    if error_message is not None:
        updates.append("error_message = %s")
        params.append(error_message)
    if local_audio_path is not None:
        updates.append("local_audio_path = %s")
        params.append(local_audio_path)
    if transcript_path is not None:
        updates.append("transcript_path = %s")
        params.append(transcript_path)
    if summary_path is not None:
        updates.append("summary_path = %s")
        params.append(summary_path)

    if status in PROCESSING_STATUSES:
        updates.append("started_at = NOW()")
    if status in ("summarized", "failed"):
        updates.append("processed_at = NOW()")

    params.append(episode_id)
    cur = conn.cursor()
    cur.execute(f"UPDATE episodes SET {', '.join(updates)} WHERE id = %s", params)
    conn.commit()
    cur.close()


def update_one_sentence(conn, episode_id: int, summary: str) -> None:
    _execute(
        conn,
        "UPDATE episodes SET one_sentence_summary = %s WHERE id = %s",
        (summary, episode_id),
    )


def reset_for_rerun(conn, episode_id: int, reset_to_status: str) -> None:
    _execute(
        conn,
        "UPDATE episodes SET status=%s, error_message=NULL, processed_at=NULL WHERE id=%s",
        (reset_to_status, episode_id),
    )


def get_pending(conn) -> list:
    return _fetchall(
        conn,
        "SELECT * FROM episodes WHERE status IN ('discovered', 'downloaded', 'transcribed') ORDER BY id",
    )


def get_unread(conn, limit: int = 20) -> list:
    return _fetchall(
        conn,
        """SELECT id, podcast_name, title, published_date, summary_path
           FROM episodes
           WHERE status = 'summarized' AND read_at IS NULL
           ORDER BY published_date DESC
           LIMIT %s""",
        (limit,),
    )


def get_by_id(conn, episode_id: int, owner: Owner) -> Optional[dict]:
    """Fetch an episode, returning None if it doesn't exist or is not owned by owner."""
    return _fetchone(
        conn,
        """SELECT e.* FROM episodes e
           JOIN podcast_feeds pf ON pf.name = e.podcast_name
           WHERE e.id = %s AND pf.owner_type = %s AND pf.owner_id = %s""",
        (episode_id, owner.type, owner.id),
    )


def mark_read(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET read_at = NOW() WHERE id = %s",
        (episode_id,),
    ) > 0


def get_stats(conn) -> list:
    return _fetchall(
        conn,
        """SELECT
               podcast_name,
               COUNT(*) as total_episodes,
               SUM(CASE WHEN status = 'summarized' AND read_at IS NULL THEN 1 ELSE 0 END) as unread_count
           FROM episodes
           GROUP BY podcast_name
           ORDER BY podcast_name""",
    )


def search(conn, query: str, search_in: str = "summaries") -> list:
    search_pattern = f"%{query}%"
    return _fetchall(
        conn,
        """SELECT id, podcast_name, title, published_date, summary_path, transcript_path
           FROM episodes
           WHERE status = 'summarized'
             AND (title LIKE %s OR description LIKE %s)
           ORDER BY published_date DESC
           LIMIT 50""",
        (search_pattern, search_pattern),
    )


def archive(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET archived_at = NOW() WHERE id = %s AND archived_at IS NULL",
        (episode_id,),
    ) > 0


def unarchive(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET archived_at = NULL WHERE id = %s AND archived_at IS NOT NULL",
        (episode_id,),
    ) > 0


def mark_read_later(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET read_later_at = NOW() WHERE id = %s AND read_later_at IS NULL",
        (episode_id,),
    ) > 0


def unmark_read_later(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET read_later_at = NULL WHERE id = %s AND read_later_at IS NOT NULL",
        (episode_id,),
    ) > 0


def delete(conn, episode_id: int) -> bool:
    return _execute(
        conn,
        "DELETE FROM episodes WHERE id = %s",
        (episode_id,),
    ) > 0


def set_transcript(conn, episode_id: int, transcript_path: str) -> bool:
    return _execute(
        conn,
        "UPDATE episodes SET transcript_path = %s, status = 'transcribed', processed_at = NOW() WHERE id = %s",
        (transcript_path, episode_id),
    ) > 0


def set_summary(
    conn,
    episode_id: int,
    summary_path: str,
    one_sentence_summary: Optional[str] = None,
) -> bool:
    cur = conn.cursor()
    if one_sentence_summary:
        cur.execute(
            "UPDATE episodes SET summary_path = %s, one_sentence_summary = %s, status = 'summarized', processed_at = NOW() WHERE id = %s",
            (summary_path, one_sentence_summary, episode_id),
        )
    else:
        cur.execute(
            "UPDATE episodes SET summary_path = %s, status = 'summarized', processed_at = NOW() WHERE id = %s",
            (summary_path, episode_id),
        )
    conn.commit()
    updated = cur.rowcount > 0
    cur.close()
    return updated


def get_all(
    conn,
    podcast_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    where, params = _filters(podcast_name, status, date_from, date_to, search)
    query = f"SELECT * FROM episodes{where} ORDER BY published_date DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_count(
    conn,
    podcast_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    where, params = _filters(podcast_name, status, date_from, date_to, search)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) as c FROM episodes{where}", params)
    count = cur.fetchone()["c"]
    cur.close()
    return count


def _filters(
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
        clauses.append("podcast_name = %s")
        params.append(podcast_name)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if date_from:
        clauses.append("published_date::DATE >= %s::DATE")
        params.append(date_from)
    if date_to:
        clauses.append("published_date::DATE <= %s::DATE")
        params.append(date_to)
    if search:
        clauses.append("(title LIKE %s OR description LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_podcast_names(conn) -> list[str]:
    return [row["podcast_name"] for row in _fetchall(conn, "SELECT DISTINCT podcast_name FROM episodes ORDER BY podcast_name")]


def get_by_podcast(conn, podcast_name: str) -> dict[str, dict]:
    rows = _fetchall(conn, "SELECT * FROM episodes WHERE podcast_name = %s", (podcast_name,))
    return {row["audio_url"]: row for row in rows}


def get_needing_one_sentence(conn) -> list:
    return _fetchall(
        conn,
        """SELECT e.id, e.description FROM episodes e
           JOIN podcast_feeds pf ON e.podcast_name = pf.name
           WHERE e.one_sentence_summary IS NULL AND e.description IS NOT NULL
             AND e.description != '' AND pf.auto_summarize = 1""",
    )
