import sqlite3
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, Response

from content_agent.db import (
    get_all_episodes,
    get_distinct_podcast_names,
    get_episode_by_id,
    get_episode_count,
    mark_episode_read,
    reset_episode_for_rerun,
)
from content_agent.web.deps import get_conn
from content_agent.web.processing import run_rerun_episode

router = APIRouter(prefix="/episodes")

PAGE_SIZE = 24


@router.get("", response_class=HTMLResponse)
def episodes_page(request: Request):
    conn = get_conn(request)
    try:
        podcast_names = get_distinct_podcast_names(conn)
        episodes = get_all_episodes(conn, limit=PAGE_SIZE, offset=0)
        total = get_episode_count(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "episodes/list.html",
        {
            "request": request,
            "episodes": episodes,
            "podcast_names": podcast_names,
            "total": total,
            "page": 1,
            "page_size": PAGE_SIZE,
            "filters": {},
        },
    )


@router.get("/search", response_class=HTMLResponse)
def episodes_search(
    request: Request,
    podcast_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
):
    offset = (page - 1) * PAGE_SIZE
    conn = get_conn(request)
    try:
        episodes = get_all_episodes(
            conn,
            podcast_name=podcast_name or None,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
            limit=PAGE_SIZE,
            offset=offset,
        )
        total = get_episode_count(
            conn,
            podcast_name=podcast_name or None,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
        )
    finally:
        conn.close()

    filters = {
        "podcast_name": podcast_name,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
    }

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "episodes/_list_partial.html",
        {
            "request": request,
            "episodes": episodes,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


@router.get("/{episode_id}", response_class=HTMLResponse)
def episode_detail(request: Request, episode_id: int):
    conn = get_conn(request)
    try:
        episode = get_episode_by_id(conn, episode_id)
    finally:
        conn.close()

    if episode is None:
        return HTMLResponse("Episode not found", status_code=404)

    summary_html = ""
    summary_text = ""
    if episode["summary_path"]:
        from pathlib import Path
        summary_file = Path(episode["summary_path"])
        if summary_file.exists():
            summary_text = summary_file.read_text()

    transcript_preview = ""
    if episode["transcript_path"]:
        from pathlib import Path
        transcript_file = Path(episode["transcript_path"])
        if transcript_file.exists():
            transcript_preview = transcript_file.read_text()[:1000]

    templates = request.app.state.templates
    summary_html = templates.env.filters["markdown"](summary_text)

    return templates.TemplateResponse(
        "episodes/detail.html",
        {
            "request": request,
            "episode": episode,
            "summary_html": summary_html,
            "transcript_preview": transcript_preview,
        },
    )


@router.post("/{episode_id}/read")
def mark_read(request: Request, episode_id: int):
    conn = get_conn(request)
    try:
        mark_episode_read(conn, episode_id)
    finally:
        conn.close()
    return Response(
        status_code=200,
        headers={"HX-Redirect": f"/episodes/{episode_id}"},
    )


def determine_reset_status(episode: sqlite3.Row) -> str:
    """Map the current episode state to the status it should be reset to for rerun."""
    status = episode["status"]
    if status == "failed":
        if episode["transcript_path"]:
            return "transcribed"
        elif episode["local_audio_path"]:
            return "downloaded"
        else:
            return "discovered"
    elif status in ("downloaded", "transcribed"):
        return status
    raise ValueError(f"Not rerunnable: status={status!r}")


@router.post("/{episode_id}/rerun", response_class=HTMLResponse)
def episode_rerun(request: Request, episode_id: int, background_tasks: BackgroundTasks):
    conn = get_conn(request)
    try:
        episode = get_episode_by_id(conn, episode_id)
        if episode is None:
            return HTMLResponse("Episode not found", status_code=404)
        reset_to = determine_reset_status(episode)
        reset_episode_for_rerun(conn, episode_id, reset_to)
        episode_dict = dict(episode)
        episode_dict["status"] = reset_to
    finally:
        conn.close()

    background_tasks.add_task(run_rerun_episode, episode_id, request.app.state.config)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "episodes/_rerun_processing.html",
        {"request": request, "episode": episode_dict},
    )


@router.get("/{episode_id}/actions", response_class=HTMLResponse)
def episode_actions(request: Request, episode_id: int):
    conn = get_conn(request)
    try:
        episode = get_episode_by_id(conn, episode_id)
        if episode is None:
            return HTMLResponse("Episode not found", status_code=404)
        episode_dict = dict(episode)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "episodes/_episode_actions.html",
        {"request": request, "episode": episode_dict},
    )
