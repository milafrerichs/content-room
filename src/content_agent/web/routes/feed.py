import asyncio
import logging
import time
from collections import defaultdict
from datetime import date, datetime
from itertools import groupby
from typing import Optional

import feedparser
from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, Response

from fastapi import HTTPException

from content_agent.feed_discovery import discover_feed
from content_agent.queries import articles, episodes, feeds, item_state, shared_items, subscriptions
from content_agent.web.auth import Owner
from content_agent.web.deps import CurrentUser, get_conn
from content_agent.web.processing import run_download_single_episode

logger = logging.getLogger(__name__)

router = APIRouter()

_rss_cache: dict[str, tuple[float, list[dict]]] = {}
_RSS_CACHE_TTL = 15 * 60


def _fetch_rss_episodes(feed_url: str) -> list[dict]:
    now = time.time()
    cached = _rss_cache.get(feed_url)
    if cached and (now - cached[0]) < _RSS_CACHE_TTL:
        return cached[1]

    parsed = feedparser.parse(feed_url)
    episode_list = []
    for entry in parsed.entries:
        audio_url = None
        for link in entry.get("links", []):
            if link.get("type", "").startswith("audio/"):
                audio_url = link["href"]
                break
        if not audio_url:
            continue
        pub_date = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed)).isoformat()
        episode_list.append({
            "title": entry.get("title", "Untitled"),
            "audio_url": audio_url,
            "published_date": pub_date,
            "duration": entry.get("itunes_duration", ""),
            "description": entry.get("description", ""),
        })

    _rss_cache[feed_url] = (now, episode_list)
    return episode_list


def _get_owned_item(conn, kind: str, item_id: int, owner, all_org_ids=None) -> Optional[dict]:
    """Visibility gate for kind-dispatched item routes. Returns None if not found or not visible."""
    if kind == "episode":
        return episodes.get_by_id(conn, item_id, owner, all_org_ids=all_org_ids)
    return articles.get_by_id(conn, item_id, owner, all_org_ids=all_org_ids)


def _feeds_context(conn, owner, all_org_ids=None, active_org_id=None):
    podcast_feed_list = feeds.get_podcasts_with_stats(conn, owner, all_org_ids=all_org_ids, active_org_id=active_org_id)
    article_feed_list = feeds.get_articles_with_stats(conn, owner, all_org_ids=all_org_ids, active_org_id=active_org_id)

    all_feeds = [
        {**f, "type": "podcast"} for f in podcast_feed_list
    ] + [
        {**f, "type": "article"} for f in article_feed_list
    ]

    all_feeds.sort(key=lambda f: (f.get("category") or "zzz", f["name"]))
    grouped = {}
    for cat, items in groupby(all_feeds, key=lambda f: f.get("category") or ""):
        grouped[cat] = list(items)

    return {"podcast_feeds": podcast_feed_list, "article_feeds": article_feed_list, "grouped_feeds": grouped}


@router.get("/feed", response_class=HTMLResponse)
def feed_page(
    request: Request,
    user: CurrentUser,
    source: Optional[str] = None,
    search: Optional[str] = None,
    view: Optional[str] = None,
    category: Optional[str] = None,
    owner: Optional[str] = None,
    kind: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn, user.owner, all_org_ids=user.all_org_ids)
        categories = feeds.get_all_categories(conn, user.owner, all_org_ids=user.all_org_ids)
        items = feeds.get_unified(
            conn, user.owner, user_id=user.user_id,
            all_org_ids=user.all_org_ids,
            source=source or None, search=search or None,
            owner_filter=owner or None, kind_filter=kind or None,
        )
    finally:
        conn.close()

    active_view = view or "timeline"

    by_day = defaultdict(list)
    for item in items:
        day = item["published_date"][:10] if item.get("published_date") else "Unknown"
        by_day[day].append(item)

    today = date.today().isoformat()
    sorted_days = sorted(by_day.keys(), reverse=True)

    by_category = defaultdict(list)
    for item in items:
        cat = item.get("category") or ""
        if category and cat != category:
            continue
        by_category[cat].append(item)

    sorted_categories = sorted(by_category.keys(), key=lambda c: (c == "", c))

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/timeline.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "grouped": by_day,
            "sorted_days": sorted_days,
            "today": today,
            "sources": sources,
            "categories": categories,
            "by_category": by_category,
            "sorted_categories": sorted_categories,
            "filters": {"source": source, "search": search, "view": active_view, "category": category, "owner": owner, "kind": kind},
        },
    )


@router.get("/archive", response_class=HTMLResponse)
def archive_page(
    request: Request,
    user: CurrentUser,
    source: Optional[str] = None,
    search: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn, user.owner, all_org_ids=user.all_org_ids)
        items = feeds.get_unified(
            conn, user.owner, user_id=user.user_id, all_org_ids=user.all_org_ids,
            source=source or None, search=search or None, archived_only=True,
        )
    finally:
        conn.close()

    by_day = defaultdict(list)
    for item in items:
        day = item["published_date"][:10] if item.get("published_date") else "Unknown"
        by_day[day].append(item)

    sorted_days = sorted(by_day.keys(), reverse=True)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/archive.html",
        {
            "request": request,
            "user": user,
            "grouped": by_day,
            "sorted_days": sorted_days,
            "sources": sources,
            "filters": {"source": source, "search": search},
        },
    )


@router.post("/feed/{kind}/{item_id}/archive", response_class=HTMLResponse)
def archive_item(request: Request, kind: str, item_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if _get_owned_item(conn, kind, item_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return HTMLResponse("", status_code=404)
        item_state.archive(conn, user.user_id, kind, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


@router.post("/feed/{kind}/{item_id}/unarchive", response_class=HTMLResponse)
def unarchive_item(request: Request, kind: str, item_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if _get_owned_item(conn, kind, item_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return HTMLResponse("", status_code=404)
        item_state.unarchive(conn, user.user_id, kind, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


def _render_feed_item(request: Request, kind: str, item_id: int, item: dict, user=None) -> Response:
    templates = request.app.state.templates
    hx_target = request.headers.get("HX-Target", "")
    if hx_target.startswith("card-"):
        template = "feed/_mobile_card.html"
    else:
        template = "feed/_feed_item.html"
    return templates.TemplateResponse(template, {"request": request, "item": item, "user": user})


@router.post("/feed/{kind}/{item_id}/read-later", response_class=HTMLResponse)
def read_later_item(request: Request, kind: str, item_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if _get_owned_item(conn, kind, item_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return HTMLResponse("", status_code=404)
        item_state.mark_read_later(conn, user.user_id, kind, item_id)
        item = feeds.get_unified_item(conn, kind, item_id, user.user_id)
    finally:
        conn.close()
    if not item:
        return HTMLResponse("")
    return _render_feed_item(request, kind, item_id, item, user=user)


@router.post("/feed/{kind}/{item_id}/unread-later", response_class=HTMLResponse)
def unread_later_item(request: Request, kind: str, item_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if _get_owned_item(conn, kind, item_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return HTMLResponse("", status_code=404)
        item_state.unmark_read_later(conn, user.user_id, kind, item_id)
        item = feeds.get_unified_item(conn, kind, item_id, user.user_id)
    finally:
        conn.close()
    if not item:
        return HTMLResponse("")
    return _render_feed_item(request, kind, item_id, item, user=user)


@router.delete("/feed/{kind}/{item_id}", response_class=HTMLResponse)
def delete_item(request: Request, kind: str, item_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if _get_owned_item(conn, kind, item_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return HTMLResponse("", status_code=404)
        if kind == "episode":
            episodes.delete(conn, item_id)
        else:
            articles.delete(conn, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


@router.get("/read-later", response_class=HTMLResponse)
def read_later_page(
    request: Request,
    user: CurrentUser,
    source: Optional[str] = None,
    search: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn, user.owner, all_org_ids=user.all_org_ids)
        items = feeds.get_unified(
            conn, user.owner, user_id=user.user_id, all_org_ids=user.all_org_ids,
            source=source or None, search=search or None, read_later_only=True,
        )
    finally:
        conn.close()

    by_day = defaultdict(list)
    for item in items:
        day = item["published_date"][:10] if item.get("published_date") else "Unknown"
        by_day[day].append(item)

    sorted_days = sorted(by_day.keys(), reverse=True)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/read_later.html",
        {
            "request": request,
            "user": user,
            "grouped": by_day,
            "sorted_days": sorted_days,
            "sources": sources,
            "filters": {"source": source, "search": search},
        },
    )


@router.get("/mobile", response_class=HTMLResponse)
def mobile_page(
    request: Request,
    user: CurrentUser,
    source: Optional[str] = None,
    search: Optional[str] = None,
    read_later: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn, user.owner, all_org_ids=user.all_org_ids)
        items = feeds.get_unified(
            conn, user.owner, user_id=user.user_id, all_org_ids=user.all_org_ids,
            source=source or None,
            search=search or None,
            read_later_only=read_later == "1",
        )
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/mobile.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "sources": sources,
            "filters": {"source": source, "search": search, "read_later": read_later},
        },
    )


@router.post("/context/switch-org")
def switch_org(request: Request, user: CurrentUser, org_id: str = Form("")):
    from fastapi.responses import RedirectResponse
    response = RedirectResponse(url="/feed", status_code=303)
    if org_id:
        response.set_cookie("active_org_id", org_id, httponly=True, samesite="lax")
    else:
        response.delete_cookie("active_org_id")
    return response


@router.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request, user: CurrentUser):
    conn = get_conn(request)
    try:
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/feeds.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/sync", response_class=HTMLResponse)
def sync_all_feeds(request: Request, user: CurrentUser):
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for pf in config.podcast_feeds:
            feeds.upsert_podcast(conn, pf.name, str(pf.url), user.owner, auto_summarize=pf.auto_summarize)
        for af in config.article_feeds:
            feeds.upsert_article(conn, af.name, str(af.url), user.owner, auto_summarize=af.auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/podcast/create", response_class=HTMLResponse)
def create_podcast_feed(
    request: Request,
    user: CurrentUser,
    name: str = Form(...),
    url: str = Form(...),
    category: str = Form(""),
    auto_summarize: bool = Form(False),
    owner_type: str = Form("user"),
):
    if owner_type == "org" and user.active_org_id and user.org_role == "org:admin":
        owner = Owner.org(user.active_org_id)
    else:
        owner = user.owner
    conn = get_conn(request)
    try:
        feeds.upsert_podcast(conn, name, url, owner, category=category or None, auto_summarize=auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/article/create", response_class=HTMLResponse)
def create_article_feed(
    request: Request,
    user: CurrentUser,
    name: str = Form(""),
    url: str = Form(...),
    category: str = Form(""),
    auto_summarize: bool = Form(False),
    owner_type: str = Form("user"),
):
    templates = request.app.state.templates

    feed_url, feed_title = discover_feed(url)
    if feed_url is None:
        return HTMLResponse(
            '<div class="text-red-600 text-sm py-2">'
            "Could not find an RSS or Atom feed at that URL."
            "</div>",
            status_code=422,
        )

    if owner_type == "org" and user.active_org_id and user.org_role == "org:admin":
        owner = Owner.org(user.active_org_id)
    else:
        owner = user.owner
    feed_name = name.strip() or feed_title or url
    conn = get_conn(request)
    try:
        feeds.upsert_article(conn, feed_name, feed_url, owner, category=category or None, auto_summarize=auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/podcast/{feed_name}/category", response_class=HTMLResponse)
def update_podcast_category(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    category: str = Form(""),
):
    conn = get_conn(request)
    try:
        feeds.update_podcast_category(conn, feed_name, user.owner, category.strip())
        conn.commit()
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/podcast/{feed_name}/auto-summarize", response_class=HTMLResponse)
def toggle_podcast_auto_summarize(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    auto_summarize: bool = Form(False),
):
    conn = get_conn(request)
    try:
        feeds.update_podcast_auto_summarize(conn, feed_name, user.owner, auto_summarize)
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/article/{feed_name}/auto-summarize", response_class=HTMLResponse)
def toggle_article_auto_summarize(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    auto_summarize: bool = Form(False),
):
    conn = get_conn(request)
    try:
        feeds.update_article_auto_summarize(conn, feed_name, user.owner, auto_summarize)
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


@router.post("/feeds/article/{feed_name}/category", response_class=HTMLResponse)
def update_article_category(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    category: str = Form(""),
):
    conn = get_conn(request)
    try:
        feeds.update_article_category(conn, feed_name, user.owner, category.strip())
        conn.commit()
        ctx = _feeds_context(conn, user.owner, all_org_ids=user.all_org_ids, active_org_id=user.active_org_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, "user": user, **ctx},
    )


def _run_download(feed_name: str, count: int, config):
    from content_agent.agent import ContentAgent

    agent = ContentAgent(config=config)
    results = asyncio.run(agent.download_podcast(feed_name, count))
    ok = sum(1 for r in results if r.success)
    logger.info("Download complete for %s: %d/%d succeeded", feed_name, ok, len(results))


@router.post("/feeds/podcast/{feed_name}/download", response_class=HTMLResponse)
def download_episodes(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
    count: int = Form(1),
):
    config = request.app.state.config
    background_tasks.add_task(_run_download, feed_name, count, config)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_download_status.html",
        {"request": request, "feed_name": feed_name, "count": count},
    )


@router.get("/feeds/podcast/{feed_name}/episodes", response_class=HTMLResponse)
def podcast_feed_detail(request: Request, feed_name: str, user: CurrentUser):
    conn = get_conn(request)
    try:
        feed_row = feeds.get_podcast_by_name(conn, feed_name, user.owner)
        if feed_row is None:
            return HTMLResponse("Feed not found", status_code=404)

        feed_url = feed_row["url"]
        rss_episodes = _fetch_rss_episodes(feed_url)

        db_episodes = episodes.get_by_podcast(conn, feed_row["id"])

        merged = []
        for ep in rss_episodes:
            db_row = db_episodes.get(ep["audio_url"])
            merged.append({
                **ep,
                "status": db_row["status"] if db_row else "new",
                "episode_id": db_row["id"] if db_row else None,
            })

        merged.sort(key=lambda e: e["published_date"], reverse=True)

    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/podcast_detail.html",
        {
            "request": request,
            "user": user,
            "feed_name": feed_name,
            "feed_url": feed_url,
            "episodes": merged,
        },
    )


@router.post("/feeds/podcast/{feed_name}/download-episode", response_class=HTMLResponse)
def download_single_episode(
    request: Request,
    feed_name: str,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
    audio_url: str = Form(...),
    title: str = Form(...),
    published_date: str = Form(""),
    duration: str = Form(""),
    description: str = Form(""),
):
    config = request.app.state.config
    conn = get_conn(request)
    try:
        feed_row = feeds.get_podcast_by_name(conn, feed_name, user.owner)
        if feed_row is None:
            return HTMLResponse("Feed not found", status_code=404)
        episodes.insert(
            conn,
            podcast_feed_id=feed_row["id"],
            title=title,
            audio_url=audio_url,
            published_date=published_date,
            duration=duration or None,
            description=description or None,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM episodes WHERE podcast_feed_id = %s AND audio_url = %s",
            (feed_row["id"], audio_url),
        )
        row = cur.fetchone()
        cur.close()
        episode_id = row["id"]
    finally:
        conn.close()

    background_tasks.add_task(run_download_single_episode, episode_id, config)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_episode_row.html",
        {
            "request": request,
            "ep": {
                "title": title,
                "audio_url": audio_url,
                "published_date": published_date,
                "duration": duration,
                "description": description,
                "status": "downloading",
                "episode_id": episode_id,
            },
            "feed_name": feed_name,
        },
    )


@router.delete("/feeds/podcast/{feed_name}", response_class=HTMLResponse)
def delete_podcast_feed(request: Request, feed_name: str, user: CurrentUser):
    conn = get_conn(request)
    try:
        feeds.delete_podcast(conn, feed_name, user.owner)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.delete("/feeds/article/{feed_name}", response_class=HTMLResponse)
def delete_article_feed(request: Request, feed_name: str, user: CurrentUser):
    conn = get_conn(request)
    try:
        feeds.delete_article(conn, feed_name, user.owner)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.get("/feeds/discover", response_class=HTMLResponse)
def discover_feeds_page(request: Request, user: CurrentUser):
    if not user.active_org_id:
        return HTMLResponse("Switch to an org context to discover shared feeds.", status_code=403)

    conn = get_conn(request)
    try:
        discoverable = subscriptions.get_discoverable_feeds(conn, user.active_org_id)
        my_sub_podcast_ids = subscriptions.get_subscriber_feed_ids(conn, "user", user.user_id, "podcast")
        my_sub_article_ids = subscriptions.get_subscriber_feed_ids(conn, "user", user.user_id, "article")
    finally:
        conn.close()

    for feed in discoverable:
        sub_ids = my_sub_podcast_ids if feed["feed_type"] == "podcast" else my_sub_article_ids
        feed["subscribed"] = feed["feed_id"] in sub_ids

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/discover.html",
        {"request": request, "user": user, "feeds": discoverable},
    )


@router.post("/feeds/{feed_type}/{feed_id}/subscribe", response_class=HTMLResponse)
def subscribe_feed(request: Request, feed_type: str, feed_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        subscriptions.subscribe(conn, "user", user.user_id, feed_type, feed_id)
    finally:
        conn.close()
    return HTMLResponse(
        f'<button hx-delete="/feeds/{feed_type}/{feed_id}/unsubscribe" '
        f'hx-target="closest div" hx-swap="outerHTML" '
        f'class="px-3 py-1.5 bg-emerald-50 text-emerald-700 border border-emerald-200 '
        f'text-xs rounded-lg hover:bg-emerald-100 transition-colors mono">Unsubscribe</button>'
    )


@router.delete("/feeds/{feed_type}/{feed_id}/unsubscribe", response_class=HTMLResponse)
def unsubscribe_feed(request: Request, feed_type: str, feed_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        subscriptions.unsubscribe(conn, "user", user.user_id, feed_type, feed_id)
    finally:
        conn.close()
    return HTMLResponse(
        f'<button hx-post="/feeds/{feed_type}/{feed_id}/subscribe" '
        f'hx-target="closest div" hx-swap="outerHTML" '
        f'class="px-3 py-1.5 bg-white text-slate-600 border border-surface-200 '
        f'text-xs rounded-lg hover:border-accent hover:text-accent transition-colors mono">Subscribe</button>'
    )


@router.post("/feeds/{feed_type}/{feed_id}/share", response_class=HTMLResponse)
def toggle_share_feed(request: Request, feed_type: str, feed_id: int, user: CurrentUser):
    if user.org_role != "org:admin":
        raise HTTPException(status_code=403, detail="Only org admins can share feeds")

    conn = get_conn(request)
    try:
        table = "podcast_feeds" if feed_type == "podcast" else "article_feeds"
        cur = conn.cursor()
        cur.execute(f"SELECT is_shared FROM {table} WHERE id = %s AND owner_type = %s AND owner_id = %s",
                    (feed_id, user.owner.type, user.owner.id))
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise HTTPException(status_code=404)
        new_shared = not row["is_shared"]
        feeds.toggle_shared(conn, feed_type, feed_id, user.owner, new_shared)
        conn.commit()
    finally:
        conn.close()

    if new_shared:
        return HTMLResponse(
            f'<button hx-post="/feeds/{feed_type}/{feed_id}/share" hx-target="this" hx-swap="outerHTML" '
            f'class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs '
            f'bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors">Shared</button>'
        )
    return HTMLResponse(
        f'<button hx-post="/feeds/{feed_type}/{feed_id}/share" hx-target="this" hx-swap="outerHTML" '
        f'class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs '
        f'bg-surface-100 text-slate-400 border border-surface-200 hover:bg-surface-200 transition-colors">Share</button>'
    )


@router.post("/feed/{kind}/{item_id}/share-to-org", response_class=HTMLResponse)
def share_item_to_org(
    request: Request,
    kind: str,
    item_id: int,
    user: CurrentUser,
    note: str = Form(""),
):
    org_id = user.active_org_id or (user.all_org_ids[0] if user.all_org_ids else None)
    if not org_id:
        return HTMLResponse("", status_code=403)
    conn = get_conn(request)
    try:
        shared_items.share_item(conn, org_id, user.user_id, kind, item_id, note or None)
    finally:
        conn.close()
    return HTMLResponse(
        f'<button id="share-btn-{kind}-{item_id}" '
        f'hx-delete="/feed/{kind}/{item_id}/share-to-org" hx-target="this" hx-swap="outerHTML" '
        f'class="p-1 text-purple-500 hover:text-purple-700 hover:bg-purple-50 rounded transition-colors" '
        f'title="Shared to Org (click to unshare)">'
        f'<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">'
        f'<path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/>'
        f'</svg></button>'
    )


@router.delete("/feed/{kind}/{item_id}/share-to-org", response_class=HTMLResponse)
def unshare_item_from_org(request: Request, kind: str, item_id: int, user: CurrentUser):
    org_id = user.active_org_id or (user.all_org_ids[0] if user.all_org_ids else None)
    if not org_id:
        return HTMLResponse("", status_code=403)
    conn = get_conn(request)
    try:
        shared_items.unshare_item(conn, org_id, kind, item_id)
    finally:
        conn.close()
    return HTMLResponse(
        f'<button id="share-btn-{kind}-{item_id}" '
        f'hx-post="/feed/{kind}/{item_id}/share-to-org" hx-target="this" hx-swap="outerHTML" '
        f'class="p-1 text-slate-400 hover:text-purple-500 hover:bg-purple-50 rounded transition-colors" '
        f'title="Share to Org">'
        f'<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" '
        f'd="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>'
        f'</svg></button>'
    )


@router.get("/org/shared", response_class=HTMLResponse)
def org_shared_page(request: Request, user: CurrentUser):
    if not user.all_org_ids:
        return HTMLResponse("You are not a member of any organization.", status_code=403)
    conn = get_conn(request)
    try:
        items = shared_items.get_shared_items(conn, user.all_org_ids)
    finally:
        conn.close()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/org_shared.html",
        {"request": request, "user": user, "items": items},
    )
