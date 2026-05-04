import asyncio

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse

from content_agent.queries import runs
from content_agent.web.deps import CurrentUser, get_conn

router = APIRouter()


def _run_processing_sync(config):
    """Sync wrapper to run the full processing pipeline in a background thread."""
    from content_agent.agent import ContentAgent

    agent = ContentAgent(config=config)
    asyncio.run(agent.run_processing())


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request, user: CurrentUser):
    conn = get_conn(request)
    try:
        stats = runs.get_dashboard_stats(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "stats": stats},
    )


@router.post("/run", response_class=HTMLResponse)
def trigger_run(request: Request, user: CurrentUser, background_tasks: BackgroundTasks):
    """Trigger the full processing pipeline (fetch feeds, download, transcribe)."""
    background_tasks.add_task(_run_processing_sync, request.app.state.config)
    return HTMLResponse(
        '<span class="mono text-xs text-emerald-600">Processing started...</span>'
    )
