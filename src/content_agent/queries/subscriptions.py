from content_agent.db import _execute, _fetchall, _fetchone


def get_discoverable_feeds(conn, org_id: str) -> list[dict]:
    """Feeds marked is_shared=true owned by the org, with subscriber counts."""
    rows = _fetchall(
        conn,
        """
        SELECT 'podcast' as feed_type, pf.id as feed_id, pf.name, pf.url, pf.category,
               (SELECT COUNT(*) FROM feed_subscriptions fs
                WHERE fs.feed_type = 'podcast' AND fs.feed_id = pf.id) as subscriber_count
        FROM podcast_feeds pf
        WHERE pf.owner_type = 'org' AND pf.owner_id = %s AND pf.is_shared = TRUE
        UNION ALL
        SELECT 'article' as feed_type, af.id as feed_id, af.name, af.url, af.category,
               (SELECT COUNT(*) FROM feed_subscriptions fs
                WHERE fs.feed_type = 'article' AND fs.feed_id = af.id) as subscriber_count
        FROM article_feeds af
        WHERE af.owner_type = 'org' AND af.owner_id = %s AND af.is_shared = TRUE
        ORDER BY name
        """,
        (org_id, org_id),
    )
    return [dict(row) for row in rows]


def subscribe(conn, subscriber_type: str, subscriber_id: str, feed_type: str, feed_id: int) -> bool:
    return _execute(
        conn,
        """INSERT INTO feed_subscriptions (subscriber_type, subscriber_id, feed_type, feed_id)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (subscriber_type, subscriber_id, feed_type, feed_id) DO NOTHING""",
        (subscriber_type, subscriber_id, feed_type, feed_id),
    ) > 0


def unsubscribe(conn, subscriber_type: str, subscriber_id: str, feed_type: str, feed_id: int) -> bool:
    return _execute(
        conn,
        """DELETE FROM feed_subscriptions
           WHERE subscriber_type = %s AND subscriber_id = %s
             AND feed_type = %s AND feed_id = %s""",
        (subscriber_type, subscriber_id, feed_type, feed_id),
    ) > 0


def get_subscriptions(conn, subscriber_type: str, subscriber_id: str) -> list[dict]:
    return [dict(row) for row in _fetchall(
        conn,
        """SELECT fs.*, pf.name, pf.url, pf.category
           FROM feed_subscriptions fs
           JOIN podcast_feeds pf ON pf.id = fs.feed_id
           WHERE fs.subscriber_type = %s AND fs.subscriber_id = %s AND fs.feed_type = 'podcast'
           UNION ALL
           SELECT fs.*, af.name, af.url, af.category
           FROM feed_subscriptions fs
           JOIN article_feeds af ON af.id = fs.feed_id
           WHERE fs.subscriber_type = %s AND fs.subscriber_id = %s AND fs.feed_type = 'article'
           ORDER BY name""",
        (subscriber_type, subscriber_id, subscriber_type, subscriber_id),
    )]


def get_subscriber_feed_ids(conn, subscriber_type: str, subscriber_id: str, feed_type: str) -> list[int]:
    rows = _fetchall(
        conn,
        """SELECT feed_id FROM feed_subscriptions
           WHERE subscriber_type = %s AND subscriber_id = %s AND feed_type = %s""",
        (subscriber_type, subscriber_id, feed_type),
    )
    return [row["feed_id"] for row in rows]
