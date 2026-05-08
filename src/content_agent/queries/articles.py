from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone
from content_agent.web.auth import Owner
from .episodes import PROCESSING_STATUSES


def insert(
    conn,
    article_feed_id: int,
    title: str,
    url: str,
    published_date: str,
    author: Optional[str] = None,
    content: Optional[str] = None,
    description: Optional[str] = None,
    canonical_feed_id: Optional[int] = None,
) -> bool:
    """Insert a new article. Returns True if inserted, False if already exists."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO articles
           (article_feed_id, title, url, published_date, author, content, description, canonical_feed_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (article_feed_id, url) DO NOTHING""",
        (article_feed_id, title, url, published_date, author, content, description, canonical_feed_id),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    cur.close()
    return inserted


def update_status(
    conn,
    article_id: int,
    status: str,
    error_message: Optional[str] = None,
    summary_path: Optional[str] = None,
) -> None:
    updates = ["status = %s"]
    params: list = [status]

    if error_message is not None:
        updates.append("error_message = %s")
        params.append(error_message)
    if summary_path is not None:
        updates.append("summary_path = %s")
        params.append(summary_path)

    if status in PROCESSING_STATUSES:
        updates.append("started_at = NOW()")
    if status in ("summarized", "failed"):
        updates.append("processed_at = NOW()")

    params.append(article_id)
    cur = conn.cursor()
    cur.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = %s", params)
    conn.commit()
    cur.close()


def update_one_sentence(conn, article_id: int, summary: str) -> None:
    _execute(
        conn,
        "UPDATE articles SET one_sentence_summary = %s WHERE id = %s",
        (summary, article_id),
    )


def get_pending(conn) -> list:
    return _fetchall(
        conn,
        """SELECT a.*, af.name as feed_name FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.status = 'discovered'
           ORDER BY a.id""",
    )


def get_unread(conn, limit: int = 20) -> list:
    return _fetchall(
        conn,
        """SELECT a.id, af.name as feed_name, a.title, a.url, a.published_date,
                  a.author, a.summary_path
           FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.status = 'summarized' AND a.read_at IS NULL
           ORDER BY a.published_date DESC
           LIMIT %s""",
        (limit,),
    )


def get_by_id(conn, article_id: int, owner: Owner, all_org_ids: Optional[list] = None) -> Optional[dict]:
    """Fetch an article visible to owner: personal ownership, org-shared feed, subscription, or individually shared to org."""
    org_clause = ""
    shared_clause = ""
    params: list = [article_id, owner.type, owner.id]
    if all_org_ids:
        placeholders = ", ".join(["%s"] * len(all_org_ids))
        org_clause = f"OR (af.owner_type = 'org' AND af.owner_id IN ({placeholders}) AND af.is_shared = TRUE)"
        params.extend(all_org_ids)
        shared_clause = f"OR a.id IN (SELECT item_id FROM shared_items WHERE item_kind = 'article' AND org_id IN ({placeholders}))"
        params.extend(all_org_ids)
    params.extend(["user", owner.id, "article"])
    return _fetchone(
        conn,
        f"""SELECT a.*, af.name as feed_name FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.id = %s AND (
               (af.owner_type = %s AND af.owner_id = %s)
               {org_clause}
               {shared_clause}
               OR af.id IN (
                   SELECT feed_id FROM feed_subscriptions
                   WHERE subscriber_type = %s AND subscriber_id = %s AND feed_type = %s
               )
           )""",
        params,
    )


def get_by_id_internal(conn, article_id: int) -> Optional[dict]:
    return _fetchone(
        conn,
        """SELECT a.*, af.name as feed_name FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.id = %s""",
        (article_id,),
    )


def get_by_id_internal(conn, article_id: int) -> Optional[dict]:
    return _fetchone(
        conn,
        """SELECT a.*, af.name as feed_name FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.id = %s""",
        (article_id,),
    )


def mark_read(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE articles SET read_at = NOW() WHERE id = %s",
        (article_id,),
    ) > 0


def archive(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE articles SET archived_at = NOW() WHERE id = %s AND archived_at IS NULL",
        (article_id,),
    ) > 0


def unarchive(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE articles SET archived_at = NULL WHERE id = %s AND archived_at IS NOT NULL",
        (article_id,),
    ) > 0


def mark_read_later(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE articles SET read_later_at = NOW() WHERE id = %s AND read_later_at IS NULL",
        (article_id,),
    ) > 0


def unmark_read_later(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "UPDATE articles SET read_later_at = NULL WHERE id = %s AND read_later_at IS NOT NULL",
        (article_id,),
    ) > 0


def delete(conn, article_id: int) -> bool:
    return _execute(
        conn,
        "DELETE FROM articles WHERE id = %s",
        (article_id,),
    ) > 0


def set_summary(
    conn,
    article_id: int,
    summary_path: str,
    one_sentence_summary: Optional[str] = None,
) -> bool:
    cur = conn.cursor()
    if one_sentence_summary:
        cur.execute(
            "UPDATE articles SET summary_path = %s, one_sentence_summary = %s, status = 'summarized', processed_at = NOW() WHERE id = %s",
            (summary_path, one_sentence_summary, article_id),
        )
    else:
        cur.execute(
            "UPDATE articles SET summary_path = %s, status = 'summarized', processed_at = NOW() WHERE id = %s",
            (summary_path, article_id),
        )
    conn.commit()
    updated = cur.rowcount > 0
    cur.close()
    return updated


def get_stats(conn) -> list:
    return _fetchall(
        conn,
        """SELECT
               af.name as feed_name,
               COUNT(*) as total_articles,
               SUM(CASE WHEN a.status = 'summarized' AND a.read_at IS NULL THEN 1 ELSE 0 END) as unread_count
           FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           GROUP BY af.id, af.name
           ORDER BY af.name""",
    )


def search(conn, query: str) -> list:
    search_pattern = f"%{query}%"
    return _fetchall(
        conn,
        """SELECT a.id, af.name as feed_name, a.title, a.url, a.published_date,
                  a.author, a.summary_path, a.content
           FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.status = 'summarized'
             AND (a.title LIKE %s OR a.description LIKE %s OR a.content LIKE %s)
           ORDER BY a.published_date DESC
           LIMIT 50""",
        (search_pattern, search_pattern, search_pattern),
    )


def get_all(
    conn,
    article_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    owner: Optional[Owner] = None,
    all_org_ids: Optional[list] = None,
) -> list:
    where, params = _filters(article_feed_id, status, date_from, date_to, search, owner=owner, all_org_ids=all_org_ids)
    query = f"""SELECT a.*, af.name as feed_name FROM articles a
                JOIN article_feeds af ON af.id = a.article_feed_id{where}
                ORDER BY a.published_date DESC LIMIT %s OFFSET %s"""
    params.extend([limit, offset])
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def get_count(
    conn,
    article_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    owner: Optional[Owner] = None,
    all_org_ids: Optional[list] = None,
) -> int:
    where, params = _filters(article_feed_id, status, date_from, date_to, search, owner=owner, all_org_ids=all_org_ids)
    cur = conn.cursor()
    cur.execute(
        f"""SELECT COUNT(*) as c FROM articles a
            JOIN article_feeds af ON af.id = a.article_feed_id{where}""",
        params,
    )
    count = cur.fetchone()["c"]
    cur.close()
    return count


def _visible_feed_clause(owner: Owner, all_org_ids: Optional[list] = None) -> tuple[str, list]:
    parts = ["(af.owner_type = %s AND af.owner_id = %s)"]
    params: list = [owner.type, owner.id]
    if all_org_ids:
        placeholders = ", ".join(["%s"] * len(all_org_ids))
        parts.append(f"(af.owner_type = 'org' AND af.owner_id IN ({placeholders}) AND af.is_shared = TRUE)")
        params.extend(all_org_ids)
    parts.append(
        "af.id IN (SELECT feed_id FROM feed_subscriptions WHERE subscriber_type = %s AND subscriber_id = %s AND feed_type = %s)"
    )
    params.extend(["user", owner.id, "article"])
    return "(" + " OR ".join(parts) + ")", params


def _filters(
    article_feed_id: Optional[int],
    status: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    search: Optional[str],
    include_archived: bool = False,
    owner: Optional[Owner] = None,
    all_org_ids: Optional[list] = None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if owner:
        clause, vis_params = _visible_feed_clause(owner, all_org_ids)
        clauses.append(clause)
        params.extend(vis_params)
    if not include_archived:
        clauses.append("a.archived_at IS NULL")
    if article_feed_id:
        clauses.append("a.article_feed_id = %s")
        params.append(article_feed_id)
    if status:
        clauses.append("a.status = %s")
        params.append(status)
    if date_from:
        clauses.append("a.published_date::DATE >= %s::DATE")
        params.append(date_from)
    if date_to:
        clauses.append("a.published_date::DATE <= %s::DATE")
        params.append(date_to)
    if search:
        clauses.append("(a.title LIKE %s OR a.description LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_feed_names(conn, owner: Optional[Owner] = None, all_org_ids: Optional[list] = None) -> list[dict]:
    if owner:
        clause, params = _visible_feed_clause(owner, all_org_ids)
        return _fetchall(
            conn,
            f"""SELECT DISTINCT af.id as article_feed_id, af.name as feed_name
               FROM articles a
               JOIN article_feeds af ON af.id = a.article_feed_id
               WHERE {clause}
               ORDER BY af.name""",
            params,
        )
    return _fetchall(
        conn,
        """SELECT DISTINCT af.id as article_feed_id, af.name as feed_name
           FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           ORDER BY af.name""",
    )


def reset_for_rerun(conn, article_id: int) -> None:
    _execute(
        conn,
        "UPDATE articles SET status='discovered', error_message=NULL, processed_at=NULL WHERE id=%s",
        (article_id,),
    )


def get_needing_one_sentence(conn) -> list:
    return _fetchall(
        conn,
        """SELECT a.id, a.content FROM articles a
           JOIN article_feeds af ON af.id = a.article_feed_id
           WHERE a.one_sentence_summary IS NULL AND a.content IS NOT NULL
             AND af.auto_summarize = 1""",
    )
