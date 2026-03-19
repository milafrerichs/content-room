import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from content_agent import ContentAgent, db

router = APIRouter(prefix="/podcasts")


def get_conn(request: Request) -> sqlite3.Connection:
    config = request.app.state.config
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("", response_class=HTMLResponse)
def podcasts_page(request: Request):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feeds = db.get_podcast_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("podcasts/list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.post("/create", response_class=HTMLResponse)
async def create_podcast(request: Request, name: str = Form(...), url: str = Form(...)):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        db.upsert_podcast_feed(conn, name, url)
        conn.commit()
        feeds = db.get_podcast_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("podcasts/_feeds_list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.post("/sync", response_class=HTMLResponse)
def sync_podcast_feeds(request: Request):
    """Sync podcast feeds from config.yaml into the database."""
    config = request.app.state.config
    conn = get_conn(request)
    try:
        for pf in config.podcast_feeds:
            db.upsert_podcast_feed(conn, pf.name, str(pf.url))
        conn.commit()
        feeds = db.get_podcast_feeds(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse("podcasts/_feeds_list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.delete("/{podcast_name}", response_class=HTMLResponse)
def delete_podcast(request: Request, podcast_name: str):
    conn = get_conn(request)
    try:
        db.delete_podcast_feed(conn, podcast_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")


@router.post("/{podcast_name}/download", response_class=HTMLResponse)
async def download_podcast(request: Request, podcast_name: str, count: int = Form(default=1)):
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
