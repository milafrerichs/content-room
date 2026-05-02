from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from content_agent import ContentAgent
from content_agent.queries import feeds
from content_agent.web.deps import CurrentUser, get_conn

router = APIRouter(prefix="/podcasts")


@router.get("", response_class=HTMLResponse)
def podcasts_page(request: Request, user: CurrentUser):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feed_list = feeds.get_podcasts(conn, "user", user.user_id)
    finally:
        conn.close()
    return templates.TemplateResponse("podcasts/list.html", {
        "request": request,
        "user": user,
        "feeds": feed_list,
    })


@router.post("/create", response_class=HTMLResponse)
async def create_podcast(request: Request, user: CurrentUser, name: str = Form(...), url: str = Form(...)):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feeds.upsert_podcast(conn, name, url, "user", user.user_id)
        conn.commit()
        feed_list = feeds.get_podcasts(conn, "user", user.user_id)
    finally:
        conn.close()
    return templates.TemplateResponse("podcasts/_feeds_list.html", {
        "request": request,
        "user": user,
        "feeds": feed_list,
    })


@router.post("/sync", response_class=HTMLResponse)
def sync_podcast_feeds(request: Request, user: CurrentUser):
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for pf in config.podcast_feeds:
            feeds.upsert_podcast(conn, pf.name, str(pf.url), "user", user.user_id)
        conn.commit()
        feed_list = feeds.get_podcasts(conn, "user", user.user_id)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse("podcasts/_feeds_list.html", {
        "request": request,
        "user": user,
        "feeds": feed_list,
    })


@router.delete("/{podcast_name}", response_class=HTMLResponse)
def delete_podcast(request: Request, podcast_name: str, user: CurrentUser):
    conn = get_conn(request)
    try:
        feeds.delete_podcast(conn, podcast_name, "user", user.user_id)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.post("/{podcast_name}/download", response_class=HTMLResponse)
async def download_podcast(request: Request, podcast_name: str, user: CurrentUser, count: int = Form(default=1)):
    config = request.app.state.config
    templates = request.app.state.templates
    agent = ContentAgent(config=config)
    try:
        results = await agent.download_podcast(podcast_name, count)
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        message = f"Done: {successful} succeeded, {failed} failed"
        error = None
    except ValueError as e:
        message = None
        error = str(e)
    return templates.TemplateResponse("podcasts/_download_result.html", {
        "request": request,
        "podcast_name": podcast_name,
        "message": message,
        "error": error,
    })
