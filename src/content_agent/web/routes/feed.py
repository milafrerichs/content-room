from typing import Optional
from collections import defaultdict
from datetime import date
from itertools import groupby

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from content_agent import db
from content_agent.web.deps import get_conn

router = APIRouter()


def _feeds_context(conn):
    """Load feeds with stats and group by category."""
    podcast_feeds = db.get_podcast_feeds_with_stats(conn)
    article_feeds = db.get_article_feeds_with_stats(conn)

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
        sources = db.get_all_feed_sources(conn)
        categories = db.get_all_feed_categories(conn)
        items = db.get_unified_feed(conn, source=source or None, search=search or None)
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
        sources = db.get_all_feed_sources(conn)
        items = db.get_unified_feed(conn, source=source or None, search=search or None, archived_only=True)
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
            db.archive_episode(conn, item_id)
        else:
            db.archive_article(conn, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


@router.post("/feed/{kind}/{item_id}/unarchive", response_class=HTMLResponse)
def unarchive_item(request: Request, kind: str, item_id: int):
    conn = get_conn(request)
    try:
        if kind == "episode":
            db.unarchive_episode(conn, item_id)
        else:
            db.unarchive_article(conn, item_id)
    finally:
        conn.close()
    return HTMLResponse("")


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
            db.upsert_podcast_feed(conn, pf.name, str(pf.url))
        for af in config.article_feeds:
            db.upsert_article_feed(conn, af.name, str(af.url))
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
):
    conn = get_conn(request)
    try:
        db.upsert_podcast_feed(conn, name, url, category=category or None)
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
    name: str = Form(...),
    url: str = Form(...),
    category: str = Form(""),
):
    conn = get_conn(request)
    try:
        db.upsert_article_feed(conn, name, url, category=category or None)
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
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
        db.update_podcast_feed_category(conn, feed_name, category.strip())
        conn.commit()
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
        db.update_article_feed_category(conn, feed_name, category.strip())
        conn.commit()
        ctx = _feeds_context(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "feed/_feeds_list.html",
        {"request": request, **ctx},
    )


@router.delete("/feeds/podcast/{feed_name}", response_class=HTMLResponse)
def delete_podcast_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        db.delete_podcast_feed(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.delete("/feeds/article/{feed_name}", response_class=HTMLResponse)
def delete_article_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        db.delete_article_feed(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")
