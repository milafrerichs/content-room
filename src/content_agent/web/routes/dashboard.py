import asyncio
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse

from content_agent.db import get_dashboard_stats
from content_agent.web.deps import get_conn

router = APIRouter()


def _run_processing_sync(config):
    """Sync wrapper to run the full processing pipeline in a background thread."""
    from content_agent.agent import ContentAgent

    agent = ContentAgent(config=config)
    asyncio.run(agent.run_processing())


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


@router.post("/run", response_class=HTMLResponse)
def trigger_run(request: Request, background_tasks: BackgroundTasks):
    """Trigger the full processing pipeline (fetch feeds, download, transcribe)."""
    background_tasks.add_task(_run_processing_sync, request.app.state.config)
    return HTMLResponse(
        '<span class="mono text-xs text-emerald-600">Processing started...</span>'
    )
