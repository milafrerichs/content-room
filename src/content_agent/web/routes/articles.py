from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, Response

from content_agent.queries import articles, feeds, item_state
from content_agent.web.deps import CurrentUser, get_conn
from content_agent.web.processing import run_rerun_article

router = APIRouter(prefix="/articles")

PAGE_SIZE = 24


@router.get("", response_class=HTMLResponse)
def articles_page(request: Request, user: CurrentUser):
    conn = get_conn(request)
    try:
        article_feeds = articles.get_feed_names(conn, owner=user.owner, all_org_ids=user.all_org_ids)
        article_list = articles.get_all(conn, limit=PAGE_SIZE, offset=0, owner=user.owner, all_org_ids=user.all_org_ids)
        total = articles.get_count(conn, owner=user.owner, all_org_ids=user.all_org_ids)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/list.html",
        {
            "request": request,
            "user": user,
            "articles": article_list,
            "article_feeds": article_feeds,
            "total": total,
            "page": 1,
            "page_size": PAGE_SIZE,
            "filters": {},
        },
    )


@router.get("/search", response_class=HTMLResponse)
def articles_search(
    request: Request,
    user: CurrentUser,
    article_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
):
    offset = (page - 1) * PAGE_SIZE
    conn = get_conn(request)
    try:
        article_list = articles.get_all(
            conn,
            article_feed_id=article_feed_id,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
            limit=PAGE_SIZE,
            offset=offset,
            owner=user.owner,
            all_org_ids=user.all_org_ids,
        )
        total = articles.get_count(
            conn,
            article_feed_id=article_feed_id,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
            owner=user.owner,
            all_org_ids=user.all_org_ids,
        )
    finally:
        conn.close()

    filters = {
        "article_feed_id": article_feed_id,
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
            "user": user,
            "articles": article_list,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


@router.get("/{article_id:int}", response_class=HTMLResponse)
def article_detail(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        article = articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids)
    finally:
        conn.close()

    if article is None:
        return HTMLResponse("Article not found", status_code=404)

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
            "user": user,
            "article": article,
            "summary_html": summary_html,
        },
    )


@router.post("/{article_id:int}/read")
def mark_read(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        item_state.mark_read(conn, user.user_id, "article", article_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/articles/{article_id}"})


@router.post("/{article_id:int}/summarize", response_class=HTMLResponse)
def article_summarize(request: Request, article_id: int, user: CurrentUser, background_tasks: BackgroundTasks):
    conn = get_conn(request)
    try:
        article = articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids)
        if article is None:
            return HTMLResponse("Article not found", status_code=404)
        articles.reset_for_rerun(conn, article_id)
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
def article_actions(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        article = articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids)
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
def archive(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        articles.archive(conn, article_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/articles/{article_id}"})


@router.post("/{article_id:int}/unarchive")
def unarchive(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if articles.get_by_id(conn, article_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        articles.unarchive(conn, article_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/articles/{article_id}"})


# =============================================================================
# Feed management
# =============================================================================


@router.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request, user: CurrentUser):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feed_list = feeds.get_articles(conn, user.owner)
    finally:
        conn.close()
    return templates.TemplateResponse(
        "articles/feeds.html",
        {"request": request, "user": user, "feeds": feed_list},
    )


@router.post("/feeds/create", response_class=HTMLResponse)
async def create_article_feed(request: Request, user: CurrentUser, name: str = Form(...), url: str = Form(...)):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feeds.upsert_article(conn, name, url, user.owner)
        conn.commit()
        feed_list = feeds.get_articles(conn, user.owner)
    finally:
        conn.close()
    return templates.TemplateResponse(
        "articles/_feeds_list.html",
        {"request": request, "user": user, "feeds": feed_list},
    )


@router.post("/feeds/sync", response_class=HTMLResponse)
def sync_article_feeds(request: Request, user: CurrentUser):
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for af in config.article_feeds:
            feeds.upsert_article(conn, af.name, str(af.url), user.owner)
        conn.commit()
        feed_list = feeds.get_articles(conn, user.owner)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "articles/_feeds_list.html",
        {"request": request, "user": user, "feeds": feed_list},
    )


@router.delete("/feeds/{feed_name}", response_class=HTMLResponse)
def delete_feed(request: Request, feed_name: str, user: CurrentUser):
    conn = get_conn(request)
    try:
        feeds.delete_article(conn, feed_name, user.owner)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")
