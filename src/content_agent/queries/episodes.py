from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone
from content_agent.web.auth import Owner

PROCESSING_STATUSES = ("downloading", "transcribing", "summarizing")


def insert(
    conn,
    podcast_feed_id: int,
    title: str,
    audio_url: str,
    published_date: str,
    duration: Optional[str] = None,
    description: Optional[str] = None,
    canonical_feed_id: Optional[int] = None,
) -> bool:
    """Insert a new episode. Returns True if inserted, False if already exists."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO episodes
           (podcast_feed_id, title, audio_url, published_date, duration, description, canonical_feed_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (podcast_feed_id, audio_url) DO NOTHING""",
        (podcast_feed_id, title, audio_url, published_date, duration, description, canonical_feed_id),
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
        """SELECT e.*, pf.name as podcast_name FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.status IN ('discovered', 'downloaded', 'transcribed')
           ORDER BY e.id""",
    )


def get_unread(conn, limit: int = 20) -> list:
    return _fetchall(
        conn,
        """SELECT e.id, pf.name as podcast_name, e.title, e.published_date, e.summary_path
           FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.status = 'summarized' AND e.read_at IS NULL
           ORDER BY e.published_date DESC
           LIMIT %s""",
        (limit,),
    )


def get_by_id(conn, episode_id: int, owner: Owner, all_org_ids: Optional[list] = None) -> Optional[dict]:
    """Fetch an episode visible to owner: personal ownership, org-shared feed, or subscription."""
    org_clause = ""
    params: list = [episode_id, owner.type, owner.id]
    if all_org_ids:
        placeholders = ", ".join(["%s"] * len(all_org_ids))
        org_clause = f"OR (pf.owner_type = 'org' AND pf.owner_id IN ({placeholders}) AND pf.is_shared = TRUE)"
        params.extend(all_org_ids)
    params.extend(["user", owner.id, "podcast"])
    return _fetchone(
        conn,
        f"""SELECT e.*, pf.name as podcast_name FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.id = %s AND (
               (pf.owner_type = %s AND pf.owner_id = %s)
               {org_clause}
               OR pf.id IN (
                   SELECT feed_id FROM feed_subscriptions
                   WHERE subscriber_type = %s AND subscriber_id = %s AND feed_type = %s
               )
           )""",
        params,
    )


def get_by_id_internal(conn, episode_id: int) -> Optional[dict]:
    return _fetchone(
        conn,
        """SELECT e.*, pf.name as podcast_name FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.id = %s""",
        (episode_id,),
    )


def get_by_id_internal(conn, episode_id: int) -> Optional[dict]:
    return _fetchone(
        conn,
        """SELECT e.*, pf.name as podcast_name FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.id = %s""",
        (episode_id,),
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
               pf.name as podcast_name,
               COUNT(*) as total_episodes,
               SUM(CASE WHEN e.status = 'summarized' AND e.read_at IS NULL THEN 1 ELSE 0 END) as unread_count
           FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           GROUP BY pf.id, pf.name
           ORDER BY pf.name""",
    )


def search(conn, query: str, search_in: str = "summaries") -> list:
    search_pattern = f"%{query}%"
    return _fetchall(
        conn,
        """SELECT e.id, pf.name as podcast_name, e.title, e.published_date,
                  e.summary_path, e.transcript_path
           FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.status = 'summarized'
             AND (e.title LIKE %s OR e.description LIKE %s)
           ORDER BY e.published_date DESC
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
    podcast_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    where, params = _filters(podcast_feed_id, status, date_from, date_to, search)
    query = f"""SELECT e.*, pf.name as podcast_name FROM episodes e
                JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id{where}
                ORDER BY e.published_date DESC LIMIT %s OFFSET %s"""
    params.extend([limit, offset])
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_count(
    conn,
    podcast_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    where, params = _filters(podcast_feed_id, status, date_from, date_to, search)
    cur = conn.cursor()
    cur.execute(
        f"""SELECT COUNT(*) as c FROM episodes e
            JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id{where}""",
        params,
    )
    count = cur.fetchone()["c"]
    cur.close()
    return count


def _filters(
    podcast_feed_id: Optional[int],
    status: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    search: Optional[str],
    include_archived: bool = False,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if not include_archived:
        clauses.append("e.archived_at IS NULL")
    if podcast_feed_id:
        clauses.append("e.podcast_feed_id = %s")
        params.append(podcast_feed_id)
    if status:
        clauses.append("e.status = %s")
        params.append(status)
    if date_from:
        clauses.append("e.published_date::DATE >= %s::DATE")
        params.append(date_from)
    if date_to:
        clauses.append("e.published_date::DATE <= %s::DATE")
        params.append(date_to)
    if search:
        clauses.append("(e.title LIKE %s OR e.description LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_podcast_names(conn) -> list[dict]:
    return _fetchall(
        conn,
        """SELECT DISTINCT pf.id as podcast_feed_id, pf.name as podcast_name
           FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           ORDER BY pf.name""",
    )


def get_by_podcast(conn, podcast_feed_id: int) -> dict[str, dict]:
    rows = _fetchall(conn, "SELECT * FROM episodes WHERE podcast_feed_id = %s", (podcast_feed_id,))
    return {row["audio_url"]: row for row in rows}


def get_needing_one_sentence(conn) -> list:
    return _fetchall(
        conn,
        """SELECT e.id, e.description FROM episodes e
           JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
           WHERE e.one_sentence_summary IS NULL AND e.description IS NOT NULL
             AND e.description != '' AND pf.auto_summarize = 1""",
    )
