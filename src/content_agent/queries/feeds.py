from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone
from content_agent.models import ArticleFeed, PodcastFeed


def get_podcasts(conn, owner_type: str, owner_id: str) -> list[PodcastFeed]:
    rows = _fetchall(
        conn,
        "SELECT name, url, category, auto_summarize FROM podcast_feeds WHERE owner_type=%s AND owner_id=%s ORDER BY name",
        (owner_type, owner_id),
    )
    return [PodcastFeed.from_row(row) for row in rows]


def upsert_podcast(
    conn,
    name: str,
    url: str,
    owner_type: str = "user",
    owner_id: str = "__legacy__",
    category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    cur = conn.cursor()
    conflict = "ON CONFLICT(owner_type, owner_id, name) DO UPDATE SET url=EXCLUDED.url"
    if category is not None and auto_summarize is not None:
        cur.execute(
            f"""INSERT INTO podcast_feeds (name, url, owner_type, owner_id, category, auto_summarize)
               VALUES (%s, %s, %s, %s, %s, %s)
               {conflict}, category=EXCLUDED.category, auto_summarize=EXCLUDED.auto_summarize""",
            (name, url, owner_type, owner_id, category, int(auto_summarize)),
        )
    elif category is not None:
        cur.execute(
            f"""INSERT INTO podcast_feeds (name, url, owner_type, owner_id, category)
               VALUES (%s, %s, %s, %s, %s)
               {conflict}, category=EXCLUDED.category""",
            (name, url, owner_type, owner_id, category),
        )
    elif auto_summarize is not None:
        cur.execute(
            f"""INSERT INTO podcast_feeds (name, url, owner_type, owner_id, auto_summarize)
               VALUES (%s, %s, %s, %s, %s)
               {conflict}, auto_summarize=EXCLUDED.auto_summarize""",
            (name, url, owner_type, owner_id, int(auto_summarize)),
        )
    else:
        cur.execute(
            f"""INSERT INTO podcast_feeds (name, url, owner_type, owner_id)
               VALUES (%s, %s, %s, %s)
               {conflict}""",
            (name, url, owner_type, owner_id),
        )
    cur.close()


def update_podcast_category(conn, name: str, owner_type: str, owner_id: str, category: str) -> None:
    _execute(
        conn,
        "UPDATE podcast_feeds SET category = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (category, name, owner_type, owner_id),
    )


def update_podcast_auto_summarize(conn, name: str, owner_type: str, owner_id: str, auto_summarize: bool) -> None:
    _execute(
        conn,
        "UPDATE podcast_feeds SET auto_summarize = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (int(auto_summarize), name, owner_type, owner_id),
    )


def delete_podcast(conn, name: str, owner_type: str, owner_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM podcast_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner_type, owner_id),
    )
    cur.close()


def get_articles(conn, owner_type: str, owner_id: str) -> list[ArticleFeed]:
    rows = _fetchall(
        conn,
        "SELECT name, url, category, auto_summarize FROM article_feeds WHERE owner_type=%s AND owner_id=%s ORDER BY name",
        (owner_type, owner_id),
    )
    return [ArticleFeed.from_row(row) for row in rows]


def upsert_article(
    conn,
    name: str,
    url: str,
    owner_type: str = "user",
    owner_id: str = "__legacy__",
    category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    cur = conn.cursor()
    conflict = "ON CONFLICT(owner_type, owner_id, name) DO UPDATE SET url=EXCLUDED.url"
    if category is not None and auto_summarize is not None:
        cur.execute(
            f"""INSERT INTO article_feeds (name, url, owner_type, owner_id, category, auto_summarize)
               VALUES (%s, %s, %s, %s, %s, %s)
               {conflict}, category=EXCLUDED.category, auto_summarize=EXCLUDED.auto_summarize""",
            (name, url, owner_type, owner_id, category, int(auto_summarize)),
        )
    elif category is not None:
        cur.execute(
            f"""INSERT INTO article_feeds (name, url, owner_type, owner_id, category)
               VALUES (%s, %s, %s, %s, %s)
               {conflict}, category=EXCLUDED.category""",
            (name, url, owner_type, owner_id, category),
        )
    elif auto_summarize is not None:
        cur.execute(
            f"""INSERT INTO article_feeds (name, url, owner_type, owner_id, auto_summarize)
               VALUES (%s, %s, %s, %s, %s)
               {conflict}, auto_summarize=EXCLUDED.auto_summarize""",
            (name, url, owner_type, owner_id, int(auto_summarize)),
        )
    else:
        cur.execute(
            f"""INSERT INTO article_feeds (name, url, owner_type, owner_id)
               VALUES (%s, %s, %s, %s)
               {conflict}""",
            (name, url, owner_type, owner_id),
        )
    cur.close()


def update_article_category(conn, name: str, owner_type: str, owner_id: str, category: str) -> None:
    _execute(
        conn,
        "UPDATE article_feeds SET category = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (category, name, owner_type, owner_id),
    )


def update_article_auto_summarize(conn, name: str, owner_type: str, owner_id: str, auto_summarize: bool) -> None:
    _execute(
        conn,
        "UPDATE article_feeds SET auto_summarize = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (int(auto_summarize), name, owner_type, owner_id),
    )


def delete_article(conn, name: str, owner_type: str, owner_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM article_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner_type, owner_id),
    )
    cur.close()


def get_podcast_by_name(conn, name: str, owner_type: str, owner_id: str) -> Optional[dict]:
    return _fetchone(
        conn,
        "SELECT * FROM podcast_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner_type, owner_id),
    )


def get_podcasts_with_stats(conn, owner_type: str, owner_id: str) -> list[dict]:
    return [dict(row) for row in _fetchall(
        conn,
        """
        SELECT pf.name, pf.url, pf.category, pf.auto_summarize,
               MAX(e.published_date) as last_item_date,
               COUNT(e.id) as item_count
        FROM podcast_feeds pf
        LEFT JOIN episodes e ON pf.name = e.podcast_name
        WHERE pf.owner_type = %s AND pf.owner_id = %s
        GROUP BY pf.id
        ORDER BY COALESCE(pf.category, 'zzz'), pf.name
        """,
        (owner_type, owner_id),
    )]


def get_articles_with_stats(conn, owner_type: str, owner_id: str) -> list[dict]:
    return [dict(row) for row in _fetchall(
        conn,
        """
        SELECT af.name, af.url, af.category, af.auto_summarize,
               MAX(a.published_date) as last_item_date,
               COUNT(a.id) as item_count
        FROM article_feeds af
        LEFT JOIN articles a ON af.name = a.feed_name
        WHERE af.owner_type = %s AND af.owner_id = %s
        GROUP BY af.id
        ORDER BY COALESCE(af.category, 'zzz'), af.name
        """,
        (owner_type, owner_id),
    )]


def get_all_sources(conn, owner_type: str, owner_id: str) -> list[str]:
    return [row["name"] for row in _fetchall(
        conn,
        """
        SELECT DISTINCT e.podcast_name as name
        FROM episodes e
        JOIN podcast_feeds pf ON pf.name = e.podcast_name
        WHERE pf.owner_type = %s AND pf.owner_id = %s
        UNION
        SELECT DISTINCT a.feed_name as name
        FROM articles a
        JOIN article_feeds af ON af.name = a.feed_name
        WHERE af.owner_type = %s AND af.owner_id = %s
        ORDER BY name
        """,
        (owner_type, owner_id, owner_type, owner_id),
    )]


def get_all_categories(conn, owner_type: str, owner_id: str) -> list[str]:
    return [row["category"] for row in _fetchall(
        conn,
        """
        SELECT DISTINCT category FROM podcast_feeds
        WHERE owner_type = %s AND owner_id = %s AND category IS NOT NULL AND category != ''
        UNION
        SELECT DISTINCT category FROM article_feeds
        WHERE owner_type = %s AND owner_id = %s AND category IS NOT NULL AND category != ''
        ORDER BY category
        """,
        (owner_type, owner_id, owner_type, owner_id),
    )]


def get_unified(
    conn,
    owner_type: str,
    owner_id: str,
    source: Optional[str] = None,
    search: Optional[str] = None,
    include_archived: bool = False,
    archived_only: bool = False,
    read_later_only: bool = False,
    limit: int = 200,
) -> list[dict]:
    clauses_ep: list[str] = ["pf.owner_type = %s AND pf.owner_id = %s"]
    clauses_art: list[str] = ["af.owner_type = %s AND af.owner_id = %s"]
    params_ep: list = [owner_type, owner_id]
    params_art: list = [owner_type, owner_id]

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
        clauses_ep.append("e.podcast_name = %s")
        params_ep.append(source)
        clauses_art.append("a.feed_name = %s")
        params_art.append(source)
    if search:
        clauses_ep.append("(e.title LIKE %s OR e.description LIKE %s)")
        params_ep.extend([f"%{search}%", f"%{search}%"])
        clauses_art.append("(a.title LIKE %s OR a.description LIKE %s)")
        params_art.extend([f"%{search}%", f"%{search}%"])

    where_ep = " AND ".join(clauses_ep)
    where_art = " AND ".join(clauses_art)

    query = f"""
        SELECT e.id, 'episode' as kind, e.podcast_name as source, e.title,
               e.published_date, e.status, e.one_sentence_summary, e.read_at,
               COALESCE(pf.category, '') as category, e.archived_at,
               e.read_later_at, e.description
        FROM episodes e
        LEFT JOIN podcast_feeds pf ON pf.name = e.podcast_name
        WHERE {where_ep}
        UNION ALL
        SELECT a.id, 'article' as kind, a.feed_name as source, a.title,
               a.published_date, a.status, a.one_sentence_summary, a.read_at,
               COALESCE(af.category, '') as category, a.archived_at,
               a.read_later_at, a.description
        FROM articles a
        LEFT JOIN article_feeds af ON af.name = a.feed_name
        WHERE {where_art}
        ORDER BY published_date DESC
        LIMIT %s
    """
    params = params_ep + params_art + [limit]
    cur = conn.cursor()
    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    cur.close()
    return rows


def get_unified_item(conn, kind: str, item_id: int) -> Optional[dict]:
    cur = conn.cursor()
    if kind == "episode":
        cur.execute(
            """SELECT e.id, 'episode' as kind, e.podcast_name as source, e.title,
                      e.published_date, e.status, e.one_sentence_summary, e.read_at,
                      COALESCE(pf.category, '') as category, e.archived_at,
                      e.read_later_at, e.description
               FROM episodes e
               LEFT JOIN podcast_feeds pf ON pf.name = e.podcast_name
               WHERE e.id = %s""",
            (item_id,),
        )
    else:
        cur.execute(
            """SELECT a.id, 'article' as kind, a.feed_name as source, a.title,
                      a.published_date, a.status, a.one_sentence_summary, a.read_at,
                      COALESCE(af.category, '') as category, a.archived_at,
                      a.read_later_at, a.description
               FROM articles a
               LEFT JOIN article_feeds af ON af.name = a.feed_name
               WHERE a.id = %s""",
            (item_id,),
        )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None
