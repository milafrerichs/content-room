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


def toggle_shared(conn, feed_type: str, feed_id: int, owner: Owner, is_shared: bool) -> bool:
    table = "podcast_feeds" if feed_type == "podcast" else "article_feeds"
    return _execute(
        conn,
        f"UPDATE {table} SET is_shared = %s WHERE id = %s AND owner_type = %s AND owner_id = %s",
        (is_shared, feed_id, owner.type, owner.id),
    ) > 0


def _owner_clause(owner: Owner, all_org_ids: Optional[list], table_alias: str) -> tuple[str, list]:
    """Build WHERE clause fragment for owner + all org memberships."""
    if all_org_ids:
        placeholders = ", ".join(["%s"] * len(all_org_ids))
        clause = (
            f"(({table_alias}.owner_type = %s AND {table_alias}.owner_id = %s)"
            f" OR ({table_alias}.owner_type = 'org' AND {table_alias}.owner_id IN ({placeholders})))"
        )
        return clause, [owner.type, owner.id] + list(all_org_ids)
    return f"{table_alias}.owner_type = %s AND {table_alias}.owner_id = %s", [owner.type, owner.id]


def get_podcasts_with_stats(conn, owner: Owner, all_org_ids: Optional[list] = None, active_org_id: Optional[str] = None) -> list[dict]:
    effective_orgs = all_org_ids or ([active_org_id] if active_org_id else [])
    owner_clause, owner_params = _owner_clause(owner, effective_orgs or None, "pf")
    return [dict(row) for row in _fetchall(
        conn,
        f"""
        SELECT pf.id, pf.name, pf.url, pf.category, pf.auto_summarize,
               pf.owner_type, pf.owner_id, pf.is_shared,
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


def get_articles_with_stats(conn, owner: Owner, all_org_ids: Optional[list] = None, active_org_id: Optional[str] = None) -> list[dict]:
    effective_orgs = all_org_ids or ([active_org_id] if active_org_id else [])
    owner_clause, owner_params = _owner_clause(owner, effective_orgs or None, "af")
    return [dict(row) for row in _fetchall(
        conn,
        f"""
        SELECT af.id, af.name, af.url, af.category, af.auto_summarize,
               af.owner_type, af.owner_id, af.is_shared,
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


def get_all_sources(conn, owner: Owner, all_org_ids: Optional[list] = None, active_org_id: Optional[str] = None) -> list[str]:
    effective_orgs = all_org_ids or ([active_org_id] if active_org_id else [])
    owner_ep, params_ep = _owner_clause(owner, effective_orgs or None, "pf")
    owner_art, params_art = _owner_clause(owner, effective_orgs or None, "af")
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


def get_all_categories(conn, owner: Owner, all_org_ids: Optional[list] = None, active_org_id: Optional[str] = None) -> list[str]:
    effective_orgs = all_org_ids or ([active_org_id] if active_org_id else [])
    owner_pf, params_pf = _owner_clause(owner, effective_orgs or None, "pf_cat")
    owner_af, params_af = _owner_clause(owner, effective_orgs or None, "af_cat")
    return [row["category"] for row in _fetchall(
        conn,
        f"""
        SELECT DISTINCT category FROM podcast_feeds pf_cat
        WHERE {owner_pf} AND category IS NOT NULL AND category != ''
        UNION
        SELECT DISTINCT category FROM article_feeds af_cat
        WHERE {owner_af} AND category IS NOT NULL AND category != ''
        ORDER BY category
        """,
        params_pf + params_af,
    )]


def _visible_feed_ids_subquery(owner: Owner, all_org_ids: Optional[list], feed_type: str) -> tuple[str, list]:
    """Build a subquery returning feed IDs visible to this user (owned + all orgs + subscribed)."""
    table = "podcast_feeds" if feed_type == "podcast" else "article_feeds"
    params: list = [owner.type, owner.id]
    org_clause = ""
    if all_org_ids:
        placeholders = ", ".join(["%s"] * len(all_org_ids))
        org_clause = f"OR (owner_type = 'org' AND owner_id IN ({placeholders}) AND is_shared = TRUE)"
        params.extend(all_org_ids)
    params.extend(["user", owner.id, feed_type])
    subquery = f"""
        SELECT id FROM {table}
        WHERE (owner_type = %s AND owner_id = %s) {org_clause}
        UNION
        SELECT feed_id FROM feed_subscriptions
        WHERE subscriber_type = %s AND subscriber_id = %s AND feed_type = %s
    """
    return subquery, params


def get_unified(
    conn,
    owner: Owner,
    user_id: str,
    all_org_ids: Optional[list] = None,
    active_org_id: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    include_archived: bool = False,
    archived_only: bool = False,
    read_later_only: bool = False,
    owner_filter: Optional[str] = None,
    kind_filter: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    effective_orgs = all_org_ids or ([active_org_id] if active_org_id else [])
    ep_sub, ep_sub_params = _visible_feed_ids_subquery(owner, effective_orgs or None, "podcast")
    art_sub, art_sub_params = _visible_feed_ids_subquery(owner, effective_orgs or None, "article")

    clauses_ep: list[str] = [f"e.podcast_feed_id IN ({ep_sub})"]
    clauses_art: list[str] = [f"a.article_feed_id IN ({art_sub})"]
    params_ep: list = list(ep_sub_params)
    params_art: list = list(art_sub_params)

    if archived_only:
        clauses_ep.append("uis_e.archived_at IS NOT NULL")
        clauses_art.append("uis_a.archived_at IS NOT NULL")
    elif not include_archived:
        clauses_ep.append("uis_e.archived_at IS NULL")
        clauses_art.append("uis_a.archived_at IS NULL")

    if read_later_only:
        clauses_ep.append("uis_e.read_later_at IS NOT NULL")
        clauses_art.append("uis_a.read_later_at IS NOT NULL")

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

    if owner_filter == "personal":
        clauses_ep.append("pf.owner_type = 'user'")
        clauses_art.append("af.owner_type = 'user'")
    elif owner_filter == "org":
        clauses_ep.append("pf.owner_type = 'org'")
        clauses_art.append("af.owner_type = 'org'")

    where_ep = " AND ".join(clauses_ep)
    where_art = " AND ".join(clauses_art)

    include_episodes = kind_filter in (None, "episode")
    include_articles = kind_filter in (None, "article")

    ep_part = f"""
        SELECT e.id, 'episode' as kind, pf.name as source, e.title,
               e.published_date, e.status, e.one_sentence_summary,
               uis_e.read_at, COALESCE(pf.category, '') as category,
               uis_e.archived_at, uis_e.read_later_at,
               e.description, pf.owner_type as source_owner_type
        FROM episodes e
        JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
        LEFT JOIN user_item_state uis_e
               ON uis_e.user_id = %s AND uis_e.item_kind = 'episode' AND uis_e.item_id = e.id
        WHERE {where_ep}
    """
    art_part = f"""
        SELECT a.id, 'article' as kind, af.name as source, a.title,
               a.published_date, a.status, a.one_sentence_summary,
               uis_a.read_at, COALESCE(af.category, '') as category,
               uis_a.archived_at, uis_a.read_later_at,
               a.description, af.owner_type as source_owner_type
        FROM articles a
        JOIN article_feeds af ON af.id = a.article_feed_id
        LEFT JOIN user_item_state uis_a
               ON uis_a.user_id = %s AND uis_a.item_kind = 'article' AND uis_a.item_id = a.id
        WHERE {where_art}
    """

    if include_episodes and include_articles:
        query = f"{ep_part} UNION ALL {art_part} ORDER BY published_date DESC LIMIT %s"
        params = [user_id] + params_ep + [user_id] + params_art + [limit]
    elif include_episodes:
        query = f"{ep_part} ORDER BY published_date DESC LIMIT %s"
        params = [user_id] + params_ep + [limit]
    else:
        query = f"{art_part} ORDER BY published_date DESC LIMIT %s"
        params = [user_id] + params_art + [limit]

    cur = conn.cursor()
    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    cur.close()
    return rows


def get_unified_item(conn, kind: str, item_id: int, user_id: str) -> Optional[dict]:
    cur = conn.cursor()
    if kind == "episode":
        cur.execute(
            """SELECT e.id, 'episode' as kind, pf.name as source, e.title,
                      e.published_date, e.status, e.one_sentence_summary,
                      uis.read_at, COALESCE(pf.category, '') as category,
                      uis.archived_at, uis.read_later_at,
                      e.description, pf.owner_type as source_owner_type
               FROM episodes e
               JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id
               LEFT JOIN user_item_state uis
                      ON uis.user_id = %s AND uis.item_kind = 'episode' AND uis.item_id = e.id
               WHERE e.id = %s""",
            (user_id, item_id),
        )
    else:
        cur.execute(
            """SELECT a.id, 'article' as kind, af.name as source, a.title,
                      a.published_date, a.status, a.one_sentence_summary,
                      uis.read_at, COALESCE(af.category, '') as category,
                      uis.archived_at, uis.read_later_at,
                      a.description, af.owner_type as source_owner_type
               FROM articles a
               JOIN article_feeds af ON af.id = a.article_feed_id
               LEFT JOIN user_item_state uis
                      ON uis.user_id = %s AND uis.item_kind = 'article' AND uis.item_id = a.id
               WHERE a.id = %s""",
            (user_id, item_id),
        )
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None
