import asyncio
import logging
import time
from datetime import datetime
from typing import Optional
from collections import defaultdict
from datetime import date
from itertools import groupby
import feedparser
from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, Response

from content_agent.queries import articles, episodes, feeds
from content_agent.feed_discovery import discover_feed
from content_agent.web.deps import get_conn
from content_agent.web.processing import run_download_single_episode

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory RSS cache: { feed_url: (timestamp, parsed_episodes) }
_rss_cache: dict[str, tuple[float, list[dict]]] = {}
_RSS_CACHE_TTL = 15 * 60  # 15 minutes


def _fetch_rss_episodes(feed_url: str) -> list[dict]:
    """Fetch and parse RSS episodes, returning cached results if fresh."""
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
            pub_date = datetime.fromtimestamp(
                time.mktime(entry.published_parsed)
            ).isoformat()

        episode_list.append({
            "title": entry.get("title", "Untitled"),
            "audio_url": audio_url,
            "published_date": pub_date,
            "duration": entry.get("itunes_duration", ""),
            "description": entry.get("description", ""),
        })

    _rss_cache[feed_url] = (now, episode_list)
    return episode_list


def _feeds_context(conn):
    """Load feeds with stats and group by category."""
    podcast_feeds = feeds.get_podcasts_with_stats(conn)
    article_feeds = feeds.get_articles_with_stats(conn)

    all_feeds = [
        {**f, "type": "podcast"} for f in podcast_feeds
    ] + [
        {**f, "type": "article"} for f in article_feeds
    ]

    # Group by category
    all_feeds.sort(key=lambda f: (f.get("category") or "zzz", f["name"]))
    grouped = {}
    for cat, items in groupby(all_feeds, key=lambda f: f.get("category") or ""):
        grouped[cat] = list(items)

    return {"podcast_feeds": podcast_feeds, "article_feeds": article_feeds, "grouped_feeds": grouped}


@router.get("/feed", response_class=HTMLResponse)
def feed_page(
    request: Request,
    source: Optional[str] = None,
    search: Optional[str] = None,
    view: Optional[str] = None,
    category: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn)
        categories = feeds.get_all_categories(conn)
        items = feeds.get_unified(conn, source=source or None, search=search or None)
    finally:
        conn.close()

    active_view = view or "timeline"

    # Group items by date
    by_day = defaultdict(list)
    for item in items:
        day = item["published_date"][:10] if item.get("published_date") else "Unknown"
        by_day[day].append(item)

    today = date.today().isoformat()
    sorted_days = sorted(by_day.keys(), reverse=True)

    # Group items by category
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
            "grouped": by_day,
            "sorted_days": sorted_days,
            "today": today,
            "sources": sources,
            "categories": categories,
            "by_category": by_category,
            "sorted_categories": sorted_categories,
            "filters": {"source": source, "search": search, "view": active_view, "category": category},
        },
    )


@router.get("/archive", response_class=HTMLResponse)
def archive_page(
    request: Request,
    source: Optional[str] = None,
    search: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn)
        items = feeds.get_unified(conn, source=source or None, search=search or None, archived_only=True)
    finally:
        conn.close()

    # Group by date
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
            "grouped": by_day,
            "sorted_days": sorted_days,
            "sources": sources,
            "filters": {"source": source, "search": search},
        },
    )


@router.post("/feed/{kind}/{item_id}/archive", response_class=HTMLResponse)
def archive_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
        if kind == "episode":
            episodes.archive(conn, item_id)
        else:
            articles.archive(conn, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


@router.post("/feed/{kind}/{item_id}/unarchive", response_class=HTMLResponse)
def unarchive_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
        if kind == "episode":
            episodes.unarchive(conn, item_id)
        else:
            articles.unarchive(conn, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


def _render_feed_item(request: Request, kind: str, item_id: int, item: dict) -> Response:
    """Return the right partial template based on which view made the request."""
    templates = request.app.state.templates
    hx_target = request.headers.get("HX-Target", "")
    if hx_target.startswith("card-"):
        template = "feed/_mobile_card.html"
    else:
        template = "feed/_feed_item.html"
    return templates.TemplateResponse(template, {"request": request, "item": item})


@router.post("/feed/{kind}/{item_id}/read-later", response_class=HTMLResponse)
def read_later_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
        if kind == "episode":
            episodes.mark_read_later(conn, item_id)
        else:
            articles.mark_read_later(conn, item_id)
        item = feeds.get_unified_item(conn, kind, item_id)
    finally:
        conn.close()
    if not item:
        return HTMLResponse("")
    return _render_feed_item(request, kind, item_id, item)


@router.post("/feed/{kind}/{item_id}/unread-later", response_class=HTMLResponse)
def unread_later_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
        if kind == "episode":
            episodes.unmark_read_later(conn, item_id)
        else:
            articles.unmark_read_later(conn, item_id)
        item = feeds.get_unified_item(conn, kind, item_id)
    finally:
        conn.close()
    if not item:
        return HTMLResponse("")
    return _render_feed_item(request, kind, item_id, item)


@router.delete("/feed/{kind}/{item_id}", response_class=HTMLResponse)
def delete_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
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
    source: Optional[str] = None,
    search: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn)
        items = feeds.get_unified(conn, source=source or None, search=search or None, read_later_only=True)
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
            "grouped": by_day,
            "sorted_days": sorted_days,
            "sources": sources,
            "filters": {"source": source, "search": search},
        },
    )


@router.get("/mobile", response_class=HTMLResponse)
def mobile_page(
    request: Request,
    source: Optional[str] = None,
    search: Optional[str] = None,
    read_later: Optional[str] = None,
):
    conn = get_conn(request)
    try:
        sources = feeds.get_all_sources(conn)
        items = feeds.get_unified(
            conn,
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
            "items": items,
            "sources": sources,
            "filters": {"source": source, "search": search, "read_later": read_later},
        },
    )


@router.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    conn = get_conn(request)
    try:
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/feeds.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/sync", response_class=HTMLResponse)
def sync_all_feeds(request: Request):
    """Sync all feeds from config.yaml into the database."""
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for pf in config.podcast_feeds:
            feeds.upsert_podcast(conn, pf.name, str(pf.url), auto_summarize=pf.auto_summarize)
        for af in config.article_feeds:
            feeds.upsert_article(conn, af.name, str(af.url), auto_summarize=af.auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/podcast/create", response_class=HTMLResponse)
def create_podcast_feed(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    category: str = Form(""),
    auto_summarize: bool = Form(False),
):
    conn = get_conn(request)
    try:
        feeds.upsert_podcast(conn, name, url, category=category or None, auto_summarize=auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/article/create", response_class=HTMLResponse)
def create_article_feed(
    request: Request,
    name: str = Form(""),
    url: str = Form(...),
    category: str = Form(""),
    auto_summarize: bool = Form(False),
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

    feed_name = name.strip() or feed_title or url
    conn = get_conn(request)
    try:
        feeds.upsert_article(conn, feed_name, feed_url, category=category or None, auto_summarize=auto_summarize)
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/podcast/{feed_name}/category", response_class=HTMLResponse)
def update_podcast_category(
    request: Request,
    feed_name: str,
    category: str = Form(""),
):
    conn = get_conn(request)
    try:
        feeds.update_podcast_category(conn, feed_name, category.strip())
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/podcast/{feed_name}/auto-summarize", response_class=HTMLResponse)
def toggle_podcast_auto_summarize(
    request: Request,
    feed_name: str,
    auto_summarize: bool = Form(False),
):
    conn = get_conn(request)
    try:
        feeds.update_podcast_auto_summarize(conn, feed_name, auto_summarize)
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/article/{feed_name}/auto-summarize", response_class=HTMLResponse)
def toggle_article_auto_summarize(
    request: Request,
    feed_name: str,
    auto_summarize: bool = Form(False),
):
    conn = get_conn(request)
    try:
        feeds.update_article_auto_summarize(conn, feed_name, auto_summarize)
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.post("/feeds/article/{feed_name}/category", response_class=HTMLResponse)
def update_article_category(
    request: Request,
    feed_name: str,
    category: str = Form(""),
):
    conn = get_conn(request)
    try:
        feeds.update_article_category(conn, feed_name, category.strip())
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


def _run_download(feed_name: str, count: int, config):
    """Background task: download N episodes for a podcast feed."""
    from content_agent.agent import ContentAgent

    agent = ContentAgent(config=config)
    results = asyncio.run(agent.download_podcast(feed_name, count))
    ok = sum(1 for r in results if r.success)
    logger.info("Download complete for %s: %d/%d succeeded", feed_name, ok, len(results))


@router.post("/feeds/podcast/{feed_name}/download", response_class=HTMLResponse)
def download_episodes(
    request: Request,
    feed_name: str,
    background_tasks: BackgroundTasks,
    count: int = Form(1),
):
    """Download N recent episodes for a podcast feed in the background."""
    config = request.app.state.config
    background_tasks.add_task(_run_download, feed_name, count, config)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_download_status.html",
        {"request": request, "feed_name": feed_name, "count": count},
    )


@router.get("/feeds/podcast/{feed_name}/episodes", response_class=HTMLResponse)
def podcast_feed_detail(request: Request, feed_name: str):
    """Show all RSS episodes for a podcast feed with DB status."""
    conn = get_conn(request)
    try:
        feed_row = feeds.get_podcast_by_name(conn, feed_name)
        if feed_row is None:
            return HTMLResponse("Feed not found", status_code=404)

        feed_url = feed_row["url"]
        rss_episodes = _fetch_rss_episodes(feed_url)

        # Look up DB status for each episode
        db_episodes = episodes.get_by_podcast(conn, feed_name)

        merged = []
        for ep in rss_episodes:
            db_row = db_episodes.get(ep["audio_url"])
            merged.append({
                **ep,
                "status": db_row["status"] if db_row else "new",
                "episode_id": db_row["id"] if db_row else None,
            })

        # Sort by published date descending
        merged.sort(key=lambda e: e["published_date"], reverse=True)

    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/podcast_detail.html",
        {
            "request": request,
            "feed_name": feed_name,
            "feed_url": feed_url,
            "episodes": merged,
        },
    )


@router.post("/feeds/podcast/{feed_name}/download-episode", response_class=HTMLResponse)
def download_single_episode(
    request: Request,
    feed_name: str,
    background_tasks: BackgroundTasks,
    audio_url: str = Form(...),
    title: str = Form(...),
    published_date: str = Form(""),
    duration: str = Form(""),
    description: str = Form(""),
):
    """Insert an episode into DB and kick off download+processing."""
    config = request.app.state.config
    conn = get_conn(request)
    try:
        episodes.insert(
            conn,
            podcast_name=feed_name,
            title=title,
            audio_url=audio_url,
            published_date=published_date,
            duration=duration or None,
            description=description or None,
        )
        # Get the episode ID
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM episodes WHERE podcast_name = %s AND audio_url = %s",
            (feed_name, audio_url),
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
def delete_podcast_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        feeds.delete_podcast(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.delete("/feeds/article/{feed_name}", response_class=HTMLResponse)
def delete_article_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        feeds.delete_article(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")
