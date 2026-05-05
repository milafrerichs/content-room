from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone


def share_item(conn, org_id: str, shared_by: str, item_kind: str, item_id: int, note: Optional[str] = None) -> bool:
    return _execute(
        conn,
        """INSERT INTO shared_items (org_id, shared_by, item_kind, item_id, note)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (org_id, item_kind, item_id) DO UPDATE SET
               note = COALESCE(EXCLUDED.note, shared_items.note),
               shared_by = EXCLUDED.shared_by,
               shared_at = NOW()""",
        (org_id, shared_by, item_kind, item_id, note),
    ) > 0


def unshare_item(conn, org_id: str, item_kind: str, item_id: int) -> bool:
    return _execute(
        conn,
        "DELETE FROM shared_items WHERE org_id = %s AND item_kind = %s AND item_id = %s",
        (org_id, item_kind, item_id),
    ) > 0


def is_shared(conn, org_id: str, item_kind: str, item_id: int) -> bool:
    row = _fetchone(
        conn,
        "SELECT 1 FROM shared_items WHERE org_id = %s AND item_kind = %s AND item_id = %s",
        (org_id, item_kind, item_id),
    )
    return row is not None


def get_shared_items(conn, org_id: str, limit: int = 100) -> list[dict]:
    rows = _fetchall(
        conn,
        """
        SELECT si.id, si.item_kind, si.item_id, si.note, si.shared_at, si.shared_by,
               u.email as sharer_email, u.display_name as sharer_name,
               CASE si.item_kind
                 WHEN 'episode' THEN e.title
                 WHEN 'article' THEN a.title
               END as title,
               CASE si.item_kind
                 WHEN 'episode' THEN pf.name
                 WHEN 'article' THEN af.name
               END as source,
               CASE si.item_kind
                 WHEN 'episode' THEN e.status
                 WHEN 'article' THEN a.status
               END as status,
               CASE si.item_kind
                 WHEN 'episode' THEN e.one_sentence_summary
                 WHEN 'article' THEN a.one_sentence_summary
               END as one_sentence_summary,
               CASE si.item_kind
                 WHEN 'episode' THEN e.published_date
                 WHEN 'article' THEN a.published_date
               END as published_date
        FROM shared_items si
        JOIN users u ON u.clerk_id = si.shared_by
        LEFT JOIN episodes e ON si.item_kind = 'episode' AND e.id = si.item_id
        LEFT JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
        LEFT JOIN articles a ON si.item_kind = 'article' AND a.id = si.item_id
        LEFT JOIN article_feeds af ON af.id = a.article_feed_id
        WHERE si.org_id = %s
        ORDER BY si.shared_at DESC
        LIMIT %s
        """,
        (org_id, limit),
    )
    return [dict(row) for row in rows]
