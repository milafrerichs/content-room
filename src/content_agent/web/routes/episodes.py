from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, Response

from content_agent.queries import episodes, item_state
from content_agent.web.deps import CurrentUser, get_conn
from content_agent.web.processing import run_rerun_episode

router = APIRouter(prefix="/episodes")

PAGE_SIZE = 24


@router.get("", response_class=HTMLResponse)
def episodes_page(request: Request, user: CurrentUser):
    conn = get_conn(request)
    try:
        podcast_feeds = episodes.get_podcast_names(conn)
        episode_list = episodes.get_all(conn, limit=PAGE_SIZE, offset=0)
        total = episodes.get_count(conn)
    finally:
        conn.close()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "episodes/list.html",
        {
            "request": request,
            "episodes": episode_list,
            "podcast_feeds": podcast_feeds,
            "total": total,
            "page": 1,
            "page_size": PAGE_SIZE,
            "filters": {},
        },
    )


@router.get("/search", response_class=HTMLResponse)
def episodes_search(
    request: Request,
    user: CurrentUser,
    podcast_feed_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
):
    offset = (page - 1) * PAGE_SIZE
    conn = get_conn(request)
    try:
        episode_list = episodes.get_all(
            conn,
            podcast_feed_id=podcast_feed_id,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
            limit=PAGE_SIZE,
            offset=offset,
        )
        total = episodes.get_count(
            conn,
            podcast_feed_id=podcast_feed_id,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            search=search or None,
        )
    finally:
        conn.close()

    filters = {
        "podcast_feed_id": podcast_feed_id,
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
            "episodes": episode_list,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "filters": filters,
        },
    )


@router.get("/{episode_id}", response_class=HTMLResponse)
def episode_detail(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        episode = episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids)
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
def mark_read(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        item_state.mark_read(conn, user.user_id, "episode", episode_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/episodes/{episode_id}"})


@router.post("/{episode_id}/archive")
def archive(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        episodes.archive(conn, episode_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/episodes/{episode_id}"})


@router.post("/{episode_id}/unarchive")
def unarchive(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        if episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids) is None:
            return Response(status_code=404)
        episodes.unarchive(conn, episode_id)
    finally:
        conn.close()
    return Response(status_code=200, headers={"HX-Redirect": f"/episodes/{episode_id}"})


def determine_reset_status(episode: dict) -> str:
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
def episode_rerun(request: Request, episode_id: int, user: CurrentUser, background_tasks: BackgroundTasks):
    conn = get_conn(request)
    try:
        episode = episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids)
        if episode is None:
            return HTMLResponse("Episode not found", status_code=404)
        reset_to = determine_reset_status(episode)
        episodes.reset_for_rerun(conn, episode_id, reset_to)
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
def episode_actions(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        episode = episodes.get_by_id(conn, episode_id, user.owner, all_org_ids=user.all_org_ids)
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
