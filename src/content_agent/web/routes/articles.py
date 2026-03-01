import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from content_agent import db

router = APIRouter(prefix="/articles")


def get_conn(request: Request) -> sqlite3.Connection:
    config = request.app.state.config
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn


@router.get("", response_class=HTMLResponse)
def articles_page(request: Request):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        feeds = db.get_article_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("articles/list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.post("/create", response_class=HTMLResponse)
async def create_article_feed(request: Request, name: str = Form(...), url: str = Form(...)):
    templates = request.app.state.templates
    conn = get_conn(request)
    try:
        db.upsert_article_feed(conn, name, url)
        conn.commit()
        feeds = db.get_article_feeds(conn)
    finally:
        conn.close()
    return templates.TemplateResponse("articles/_feeds_list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.delete("/{feed_name}", response_class=HTMLResponse)
def delete_article_feed(request: Request, feed_name: str):
    conn = get_conn(request)
    try:
        db.delete_article_feed(conn, feed_name)
        conn.commit()
    finally:
        conn.close()
    return HTMLResponse("")
