from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, Response

from content_agent import db
from content_agent.db import (
    archive_article,
    get_all_articles,
    get_article_by_id,
    get_article_count,
    get_article_feeds,
    get_distinct_feed_names,
    mark_article_read,
    reset_article_for_rerun,
    unarchive_article,
    upsert_article_feed,
    delete_article_feed,
)
from content_agent.web.deps import get_conn
from content_agent.web.processing import run_rerun_article

router = APIRouter(prefix="/articles")

PAGE_SIZE = 24


# =============================================================================
# Article browsing
# =============================================================================


@router.get("", response_class=HTMLResponse)
def articles_page(request: Request):
    conn = get_conn(request)
    try:
        feed_names = get_distinct_feed_names(conn)
        articles = get_all_articles(conn, limit=PAGE_SIZE, offset=0)
        total = get_article_count(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/list.html",
        {
            "request": request,
            "articles": articles,
            "feed_names": feed_names,
            "total": total,
            "page": 1,
            "page_size": PAGE_SIZE,
            "filters": {},
        },
    )


@router.get("/search", response_class=HTMLResponse)
def articles_search(
    request: Request,
    feed_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
):
    offset = (page - 1) * PAGE_SIZE
    conn = get_conn(request)
    try:
        articles = get_all_articles(
            conn,
            feed_name=feed_name or None,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
            limit=PAGE_SIZE,
            offset=offset,
        )
        total = get_article_count(
            conn,
            feed_name=feed_name or None,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
        )
    finally:
        conn.close()

    filters = {
        "feed_name": feed_name,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
    }

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/_article_table.html",
        {
            "request": request,
            "articles": articles,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


@router.get("/{article_id:int}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int):
    conn = get_conn(request)
    try:
        article = get_article_by_id(conn, article_id)
    finally:
        conn.close()

    if article is None:
        return HTMLResponse("Article not found", status_code=404)

    summary_html = ""
    summary_text = ""
    if article["summary_path"]:
        from pathlib import Path

        summary_file = Path(article["summary_path"])
        if summary_file.exists():
            summary_text = summary_file.read_text()

    templates = request.app.state.templates
    summary_html = templates.env.filters["markdown"](summary_text)

    return templates.TemplateResponse(
        "articles/detail.html",
        {
            "request": request,
            "article": article,
            "summary_html": summary_html,
        },
    )


@router.post("/{article_id:int}/read")
def mark_read(request: Request, article_id: int):
    conn = get_conn(request)
    try:
        mark_article_read(conn, article_id)
    finally:
        conn.close()
    return Response(
        status_code=200,
        headers={"HX-Redirect": f"/articles/{article_id}"},
    )


@router.post("/{article_id:int}/summarize", response_class=HTMLResponse)
def article_summarize(request: Request, article_id: int, background_tasks: BackgroundTasks):
    conn = get_conn(request)
    try:
        article = get_article_by_id(conn, article_id)
        if article is None:
            return HTMLResponse("Article not found", status_code=404)
        reset_article_for_rerun(conn, article_id)
        article_dict = dict(article)
        article_dict["status"] = "discovered"
    finally:
        conn.close()

    background_tasks.add_task(run_rerun_article, article_id, request.app.state.config)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/_summarize_processing.html",
        {"request": request, "article": article_dict},
    )


@router.get("/{article_id:int}/actions", response_class=HTMLResponse)
def article_actions(request: Request, article_id: int):
    conn = get_conn(request)
    try:
        article = get_article_by_id(conn, article_id)
        if article is None:
            return HTMLResponse("Article not found", status_code=404)
        article_dict = dict(article)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/_article_actions.html",
        {"request": request, "article": article_dict},
    )


@router.post("/{article_id:int}/archive")
def archive(request: Request, article_id: int):
    conn = get_conn(request)
    try:
        archive_article(conn, article_id)
    finally:
        conn.close()
    return Response(
        status_code=200,
        headers={"HX-Redirect": f"/articles/{article_id}"},
    )


@router.post("/{article_id:int}/unarchive")
def unarchive(request: Request, article_id: int):
    conn = get_conn(request)
    try:
        unarchive_article(conn, article_id)
    finally:
        conn.close()
    return Response(
        status_code=200,
        headers={"HX-Redirect": f"/articles/{article_id}"},
    )


# =============================================================================
# Feed management
# =============================================================================


@router.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feeds = get_article_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        "articles/feeds.html",
        {"request": request, "feeds": feeds},
    )


@router.post("/feeds/create", response_class=HTMLResponse)
async def create_article_feed(request: Request, name: str = Form(...), url: str = Form(...)):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        upsert_article_feed(conn, name, url)
        conn.commit()
        feeds = get_article_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        "articles/_feeds_list.html",
        {"request": request, "feeds": feeds},
    )


@router.post("/feeds/sync", response_class=HTMLResponse)
def sync_article_feeds(request: Request):
    """Sync article feeds from config.yaml into the database."""
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for af in config.article_feeds:
            upsert_article_feed(conn, af.name, str(af.url))
        conn.commit()
        feeds = get_article_feeds(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/_feeds_list.html",
        {"request": request, "feeds": feeds},
    )


@router.delete("/feeds/{feed_name}", response_class=HTMLResponse)
def delete_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        delete_article_feed(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")
