from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from content_agent.db import (
    get_all_episodes,
    get_distinct_podcast_names,
    get_episode_by_id,
    get_episode_count,
    mark_episode_read,
)
from content_agent.web.deps import get_conn

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
