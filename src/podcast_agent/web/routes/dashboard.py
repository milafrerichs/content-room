import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from podcast_agent.db import get_dashboard_stats
from podcast_agent.web.deps import get_conn

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request):
    conn = get_conn(request)
    try:
        stats = get_dashboard_stats(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "stats": stats},
    )
