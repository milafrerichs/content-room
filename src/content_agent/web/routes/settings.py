from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from content_agent.queries import settings as qs
from content_agent.models import TASK_LABELS, TASK_NAMES, TaskModelOverride
from content_agent.web.deps import CurrentUser, get_conn

router = APIRouter(prefix="/settings", tags=["settings"])


def _build_task_rows(config, db_overrides: dict) -> list[dict]:
    """Build display data for each task row."""
    rows = []
    for name in TASK_NAMES:
        override = db_overrides.get(name) or config.task_models.get(name)
        is_db = name in db_overrides
        is_yaml = not is_db and name in config.task_models
        rows.append({
            "name": name,
            "label": TASK_LABELS[name],
            "provider": override.provider if override else None,
            "model": override.model if override else None,
            "source": "db" if is_db else ("yaml" if is_yaml else "default"),
        })
    return rows


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, user: CurrentUser):
    config = request.app.state.config
    conn = get_conn(request)
    try:
        db_overrides = qs.get_task_overrides(conn)
    finally:
        conn.close()

    task_rows = _build_task_rows(config, db_overrides)
    templates = request.app.state.templates
    return templates.TemplateResponse("settings/settings.html", {
        "request": request,
        "user": user,
        "config": config,
        "task_rows": task_rows,
    })


@router.post("/task-model/{task_name}", response_class=HTMLResponse)
def save_task_model(
    request: Request,
    task_name: str,
    user: CurrentUser,
    provider: str = Form(""),
    model: str = Form(""),
):
    if task_name not in TASK_NAMES:
        return HTMLResponse("Invalid task name", status_code=400)

    override = TaskModelOverride(
        provider=provider if provider else None,
        model=model if model else None,
    )

    conn = get_conn(request)
    try:
        qs.set_task_override(conn, task_name, override)
        db_overrides = qs.get_task_overrides(conn)
    finally:
        conn.close()

    config = request.app.state.config
    # Merge DB override into config for immediate effect
    config.task_models[task_name] = override

    task_rows = _build_task_rows(config, db_overrides)
    row = next(r for r in task_rows if r["name"] == task_name)

    templates = request.app.state.templates
    return templates.TemplateResponse("settings/_task_model_row.html", {
        "request": request,
        "row": row,
        "config": config,
    })


@router.delete("/task-model/{task_name}", response_class=HTMLResponse)
def delete_task_model(request: Request, task_name: str, user: CurrentUser):
    if task_name not in TASK_NAMES:
        return HTMLResponse("Invalid task name", status_code=400)

    conn = get_conn(request)
    try:
        qs.delete_task_override(conn, task_name)
        db_overrides = qs.get_task_overrides(conn)
    finally:
        conn.close()

    config = request.app.state.config
    config.task_models.pop(task_name, None)

    task_rows = _build_task_rows(config, db_overrides)
    row = next(r for r in task_rows if r["name"] == task_name)

    templates = request.app.state.templates
    return templates.TemplateResponse("settings/_task_model_row.html", {
        "request": request,
        "row": row,
        "config": config,
    })
