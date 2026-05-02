from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from content_agent.queries import runs
from content_agent.web.deps import get_conn

router = APIRouter()


@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request):
    conn = get_conn(request)
    try:
        runs_list = runs.get_all(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "runs/list.html",
        {"request": request, "runs": runs_list},
    )
