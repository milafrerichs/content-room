from content_agent.db import _fetchall


def get_items_for_date(conn, target_date) -> list[dict]:
    """Return all summarized articles and episodes published on target_date.

    target_date: a datetime.date or ISO string (YYYY-MM-DD).
    Returns list of dicts with keys: title, feed_name, published_date,
    one_sentence_summary, item_type.
    """
    date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    return _fetchall(
        conn,
        """
        SELECT title, feed_name, published_date, one_sentence_summary, 'article' AS item_type
        FROM articles
        WHERE published_date::DATE = %s::DATE AND status = 'summarized'
        UNION ALL
        SELECT title, podcast_name AS feed_name, published_date, one_sentence_summary, 'episode' AS item_type
        FROM episodes
        WHERE published_date::DATE = %s::DATE AND status = 'summarized'
        ORDER BY published_date DESC
        """,
        (date_str, date_str),
    )
