from typing import Optional

from content_agent.db import _execute, _fetchall, _fetchone
from content_agent.models import ArticleFeed, PodcastFeed
from content_agent.web.auth import Owner


def get_podcasts(conn, owner: Owner) -> list[PodcastFeed]:
    rows = _fetchall(
        conn,
        "SELECT id, name, url, category, auto_summarize FROM podcast_feeds WHERE owner_type=%s AND owner_id=%s ORDER BY name",
        (owner.type, owner.id),
    )
    return [PodcastFeed.from_row(row) for row in rows]


def get_articles(conn, owner: Owner) -> list[ArticleFeed]:
    rows = _fetchall(
        conn,
        "SELECT id, name, url, category, auto_summarize FROM article_feeds WHERE owner_type=%s AND owner_id=%s ORDER BY name",
        (owner.type, owner.id),
    )
    return [ArticleFeed.from_row(row) for row in rows]


def _upsert_feed(conn, table: str, name: str, url: str, owner: Owner, **optional) -> None:
    cols: dict = {"name": name, "url": url, "owner_type": owner.type, "owner_id": owner.id}
    for key, val in optional.items():
        if val is not None:
            cols[key] = int(val) if key == "auto_summarize" else val

    col_names = list(cols.keys())
    placeholders = ", ".join(["%s"] * len(col_names))
    update_cols = [c for c in col_names if c not in ("name", "owner_type", "owner_id")]
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({placeholders})"
        f" ON CONFLICT(owner_type, owner_id, name) DO UPDATE SET {updates}"
    )
    cur = conn.cursor()
    cur.execute(sql, list(cols.values()))
    cur.close()


def upsert_podcast(
    conn,
    name: str,
    url: str,
    owner: Owner,
    category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    _upsert_feed(conn, "podcast_feeds", name, url, owner, category=category, auto_summarize=auto_summarize)


def upsert_article(
    conn,
    name: str,
    url: str,
    owner: Owner,
    category: Optional[str] = None,
    auto_summarize: Optional[bool] = None,
) -> None:
    _upsert_feed(conn, "article_feeds", name, url, owner, category=category, auto_summarize=auto_summarize)


def update_podcast_category(conn, name: str, owner: Owner, category: str) -> None:
    _execute(
        conn,
        "UPDATE podcast_feeds SET category = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (category, name, owner.type, owner.id),
    )


def update_podcast_auto_summarize(conn, name: str, owner: Owner, auto_summarize: bool) -> None:
    _execute(
        conn,
        "UPDATE podcast_feeds SET auto_summarize = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (int(auto_summarize), name, owner.type, owner.id),
    )


def delete_podcast(conn, name: str, owner: Owner) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM podcast_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner.type, owner.id),
    )
    cur.close()


def update_article_category(conn, name: str, owner: Owner, category: str) -> None:
    _execute(
        conn,
        "UPDATE article_feeds SET category = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (category, name, owner.type, owner.id),
    )


def update_article_auto_summarize(conn, name: str, owner: Owner, auto_summarize: bool) -> None:
    _execute(
        conn,
        "UPDATE article_feeds SET auto_summarize = %s WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (int(auto_summarize), name, owner.type, owner.id),
    )


def delete_article(conn, name: str, owner: Owner) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM article_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner.type, owner.id),
    )
    cur.close()


def get_all_podcasts(conn) -> list[PodcastFeed]:
    rows = _fetchall(conn, "SELECT id, name, url, category, auto_summarize FROM podcast_feeds ORDER BY name")
    return [PodcastFeed.from_row(row) for row in rows]


def get_all_articles(conn) -> list[ArticleFeed]:
    rows = _fetchall(conn, "SELECT id, name, url, category, auto_summarize FROM article_feeds ORDER BY name")
    return [ArticleFeed.from_row(row) for row in rows]


def get_podcast_by_name(conn, name: str, owner: Owner) -> Optional[dict]:
    return _fetchone(
        conn,
        "SELECT * FROM podcast_feeds WHERE name = %s AND owner_type = %s AND owner_id = %s",
        (name, owner.type, owner.id),
    )


def _owner_clause(owner: Owner, active_org_id: Optional[str], table_alias: str) -> tuple[str, list]:
    """Build WHERE clause fragment for owner + optional org visibility."""
    if active_org_id:
        clause = f"(({table_alias}.owner_type = %s AND {table_alias}.owner_id = %s) OR ({table_alias}.owner_type = 'org' AND {table_alias}.owner_id = %s))"
        return clause, [owner.type, owner.id, active_org_id]
    return f"{table_alias}.owner_type = %s AND {table_alias}.owner_id = %s", [owner.type, owner.id]


def get_podcasts_with_stats(conn, owner: Owner, active_org_id: Optional[str] = None) -> list[dict]:
    owner_clause, owner_params = _owner_clause(owner, active_org_id, "pf")
    return [dict(row) for row in _fetchall(
        conn,
        f"""
        SELECT pf.id, pf.name, pf.url, pf.category, pf.auto_summarize,
               pf.owner_type, pf.owner_id,
               MAX(e.published_date) as last_item_date,
               COUNT(e.id) as item_count
        FROM podcast_feeds pf
        LEFT JOIN episodes e ON pf.id = e.podcast_feed_id
        WHERE {owner_clause}
        GROUP BY pf.id
        ORDER BY COALESCE(pf.category, 'zzz'), pf.name
        """,
        owner_params,
    )]


def get_articles_with_stats(conn, owner: Owner, active_org_id: Optional[str] = None) -> list[dict]:
    owner_clause, owner_params = _owner_clause(owner, active_org_id, "af")
    return [dict(row) for row in _fetchall(
        conn,
        f"""
        SELECT af.id, af.name, af.url, af.category, af.auto_summarize,
               af.owner_type, af.owner_id,
               MAX(a.published_date) as last_item_date,
               COUNT(a.id) as item_count
        FROM article_feeds af
        LEFT JOIN articles a ON af.id = a.article_feed_id
        WHERE {owner_clause}
        GROUP BY af.id
        ORDER BY COALESCE(af.category, 'zzz'), af.name
        """,
        owner_params,
    )]


def get_all_sources(conn, owner: Owner, active_org_id: Optional[str] = None) -> list[str]:
    owner_ep, params_ep = _owner_clause(owner, active_org_id, "pf")
    owner_art, params_art = _owner_clause(owner, active_org_id, "af")
    return [row["name"] for row in _fetchall(
        conn,
        f"""
        SELECT DISTINCT pf.name as name
        FROM episodes e
        JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
        WHERE {owner_ep}
        UNION
        SELECT DISTINCT af.name as name
        FROM articles a
        JOIN article_feeds af ON af.id = a.article_feed_id
        WHERE {owner_art}
        ORDER BY name
        """,
        params_ep + params_art,
    )]


def get_all_categories(conn, owner: Owner, active_org_id: Optional[str] = None) -> list[str]:
    if active_org_id:
        return [row["category"] for row in _fetchall(
            conn,
            """
            SELECT DISTINCT category FROM podcast_feeds
            WHERE ((owner_type = %s AND owner_id = %s) OR (owner_type = 'org' AND owner_id = %s))
              AND category IS NOT NULL AND category != ''
            UNION
            SELECT DISTINCT category FROM article_feeds
            WHERE ((owner_type = %s AND owner_id = %s) OR (owner_type = 'org' AND owner_id = %s))
              AND category IS NOT NULL AND category != ''
            ORDER BY category
            """,
            (owner.type, owner.id, active_org_id, owner.type, owner.id, active_org_id),
        )]
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
        (owner.type, owner.id, owner.type, owner.id),
    )]


def get_unified(
    conn,
    owner: Owner,
    active_org_id: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    include_archived: bool = False,
    archived_only: bool = False,
    read_later_only: bool = False,
    limit: int = 200,
) -> list[dict]:
    owner_ep, params_ep_owner = _owner_clause(owner, active_org_id, "pf")
    owner_art, params_art_owner = _owner_clause(owner, active_org_id, "af")

    clauses_ep: list[str] = [owner_ep]
    clauses_art: list[str] = [owner_art]
    params_ep: list = list(params_ep_owner)
    params_art: list = list(params_art_owner)

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
        clauses_ep.append("pf.name = %s")
        params_ep.append(source)
        clauses_art.append("af.name = %s")
        params_art.append(source)

    if search:
        clauses_ep.append("(e.title ILIKE %s OR e.description ILIKE %s)")
        params_ep.extend([f"%{search}%", f"%{search}%"])
        clauses_art.append("(a.title ILIKE %s OR a.description ILIKE %s)")
        params_art.extend([f"%{search}%", f"%{search}%"])

    where_ep = " AND ".join(clauses_ep)
    where_art = " AND ".join(clauses_art)

    query = f"""
        SELECT e.id, 'episode' as kind, pf.name as source, e.title,
               e.published_date, e.status, e.one_sentence_summary, e.read_at,
               COALESCE(pf.category, '') as category, e.archived_at,
               e.read_later_at, e.description, pf.owner_type as source_owner_type
        FROM episodes e
        JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
        WHERE {where_ep}
        UNION ALL
        SELECT a.id, 'article' as kind, af.name as source, a.title,
               a.published_date, a.status, a.one_sentence_summary, a.read_at,
               COALESCE(af.category, '') as category, a.archived_at,
               a.read_later_at, a.description, af.owner_type as source_owner_type
        FROM articles a
        JOIN article_feeds af ON af.id = a.article_feed_id
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
            """SELECT e.id, 'episode' as kind, pf.name as source, e.title,
                      e.published_date, e.status, e.one_sentence_summary, e.read_at,
                      COALESCE(pf.category, '') as category, e.archived_at,
                      e.read_later_at, e.description, pf.owner_type as source_owner_type
               FROM episodes e
               JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
               WHERE e.id = %s""",
            (item_id,),
        )
    else:
        cur.execute(
            """SELECT a.id, 'article' as kind, af.name as source, a.title,
                      a.published_date, a.status, a.one_sentence_summary, a.read_at,
                      COALESCE(af.category, '') as category, a.archived_at,
                      a.read_later_at, a.description, af.owner_type as source_owner_type
               FROM articles a
               JOIN article_feeds af ON af.id = a.article_feed_id
               WHERE a.id = %s""",
            (item_id,),
        )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None
