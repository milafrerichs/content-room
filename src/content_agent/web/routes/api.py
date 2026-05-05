import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from content_agent.db import _fetchall
from content_agent.queries import articles, episodes
from content_agent.web.deps import CurrentUser, get_conn
from content_agent.web.processing import (
    run_rerun_article,
    run_summarize_episode,
    run_transcribe_episode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SummaryBody(BaseModel):
    summary: str
    one_sentence_summary: Optional[str] = None


class ActionResponse(BaseModel):
    id: int
    status: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """Sanitise a string for use as a filename."""
    return re.sub(r'[^\w\s\-.]', '', name).strip().replace(' ', '_')[:120]


def _episode_dict(row) -> dict:
    return {
        "id": row["id"],
        "kind": "episode",
        "podcast_name": row["podcast_name"],
        "title": row["title"],
        "status": row["status"],
        "published_date": row["published_date"],
        "transcript_path": row["transcript_path"],
        "summary_path": row["summary_path"],
        "one_sentence_summary": row["one_sentence_summary"],
        "error_message": row["error_message"],
    }


def _article_dict(row) -> dict:
    return {
        "id": row["id"],
        "kind": "article",
        "feed_name": row["feed_name"],
        "title": row["title"],
        "status": row["status"],
        "published_date": row["published_date"],
        "summary_path": row["summary_path"],
        "one_sentence_summary": row["one_sentence_summary"],
        "error_message": row["error_message"],
    }


# ===================================================================
# Episode endpoints
# ===================================================================

@router.get("/episodes")
def list_episodes(
    request: Request,
    user: CurrentUser,
    status: Optional[str] = None,
    podcast_feed_id: Optional[int] = None,
    limit: int = 100,
):
    conn = get_conn(request)
    try:
        clauses = []
        params: list = []
        if status:
            clauses.append("e.status = %s")
            params.append(status)
        if podcast_feed_id:
            clauses.append("e.podcast_feed_id = %s")
            params.append(podcast_feed_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = _fetchall(
            conn,
            f"""SELECT e.*, pf.name as podcast_name FROM episodes e
                JOIN podcast_feeds pf ON pf.id = e.podcast_feed_id{where}
                ORDER BY e.published_date DESC LIMIT %s""",
            params + [limit],
        )
        return [_episode_dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/episodes/{episode_id}/status")
def episode_status(request: Request, episode_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        row = episodes.get_by_id(conn, episode_id, user.owner)
        if not row:
            return JSONResponse({"error": "Episode not found"}, status_code=404)
        return _episode_dict(row)
    finally:
        conn.close()


@router.post("/episodes/{episode_id}/transcribe")
def trigger_transcribe(
    request: Request, episode_id: int, user: CurrentUser, background_tasks: BackgroundTasks
):
    conn = get_conn(request)
    try:
        row = episodes.get_by_id(conn, episode_id, user.owner)
        if not row:
            return JSONResponse({"error": "Episode not found"}, status_code=404)
        if row["status"] in ("transcribed", "summarized", "summarizing"):
            return JSONResponse(
                {"error": f"Episode already {row['status']}", "id": episode_id, "status": row["status"]},
                status_code=409,
            )
        config = request.app.state.config
    finally:
        conn.close()
    background_tasks.add_task(run_transcribe_episode, episode_id, config)
    return ActionResponse(id=episode_id, status="transcribing", message="Transcription started")


@router.post("/episodes/{episode_id}/transcript")
async def provide_transcript(
    request: Request,
    episode_id: int,
    user: CurrentUser,
    transcript_file: Optional[UploadFile] = File(None),
):
    conn = get_conn(request)
    try:
        row = episodes.get_by_id(conn, episode_id, user.owner)
        if not row:
            return JSONResponse({"error": "Episode not found"}, status_code=404)

        # Determine input: file upload (multipart) or JSON body
        if transcript_file and transcript_file.filename:
            transcript_text = (await transcript_file.read()).decode("utf-8")
        else:
            # Try to parse JSON body
            try:
                body = await request.json()
                transcript_text = body.get("transcript", "")
            except Exception:
                transcript_text = ""

        if not transcript_text:
            return JSONResponse(
                {"error": "Provide 'transcript' in JSON body or upload 'transcript_file'"},
                status_code=400,
            )

        config = request.app.state.config
        safe_title = _safe_filename(row["title"])
        transcript_path = config.transcript_dir / f"{safe_title}.txt"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)

        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)

        episodes.set_transcript(conn, episode_id, str(transcript_path))
        return ActionResponse(id=episode_id, status="transcribed", message="Transcript stored")
    finally:
        conn.close()


@router.post("/episodes/{episode_id}/summarize")
def trigger_summarize_episode(
    request: Request, episode_id: int, user: CurrentUser, background_tasks: BackgroundTasks
):
    conn = get_conn(request)
    try:
        row = episodes.get_by_id(conn, episode_id, user.owner)
        if not row:
            return JSONResponse({"error": "Episode not found"}, status_code=404)
        if row["status"] != "transcribed":
            return JSONResponse(
                {"error": f"Episode must be transcribed first (current: {row['status']})", "id": episode_id, "status": row["status"]},
                status_code=409,
            )
        config = request.app.state.config
    finally:
        conn.close()
    background_tasks.add_task(run_summarize_episode, episode_id, config)
    return ActionResponse(id=episode_id, status="summarizing", message="Summarization started")


@router.post("/episodes/{episode_id}/summary")
def provide_episode_summary(request: Request, episode_id: int, user: CurrentUser, body: SummaryBody):
    conn = get_conn(request)
    try:
        row = episodes.get_by_id(conn, episode_id, user.owner)
        if not row:
            return JSONResponse({"error": "Episode not found"}, status_code=404)

        config = request.app.state.config
        safe_title = _safe_filename(row["title"])
        summary_path = config.podcast_summary_dir / f"{safe_title}_summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(body.summary)

        episodes.set_summary(conn, episode_id, str(summary_path), body.one_sentence_summary)
        return ActionResponse(id=episode_id, status="summarized", message="Summary stored")
    finally:
        conn.close()


# ===================================================================
# Article endpoints
# ===================================================================

@router.get("/articles")
def list_articles(
    request: Request,
    user: CurrentUser,
    status: Optional[str] = None,
    article_feed_id: Optional[int] = None,
    limit: int = 100,
):
    conn = get_conn(request)
    try:
        clauses = []
        params: list = []
        if status:
            clauses.append("a.status = %s")
            params.append(status)
        if article_feed_id:
            clauses.append("a.article_feed_id = %s")
            params.append(article_feed_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = _fetchall(
            conn,
            f"""SELECT a.*, af.name as feed_name FROM articles a
                JOIN article_feeds af ON af.id = a.article_feed_id{where}
                ORDER BY a.published_date DESC LIMIT %s""",
            params + [limit],
        )
        return [_article_dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/articles/{article_id}/status")
def article_status(request: Request, article_id: int, user: CurrentUser):
    conn = get_conn(request)
    try:
        row = articles.get_by_id(conn, article_id, user.owner)
        if not row:
            return JSONResponse({"error": "Article not found"}, status_code=404)
        return _article_dict(row)
    finally:
        conn.close()


@router.post("/articles/{article_id}/summarize")
def trigger_summarize_article(
    request: Request, article_id: int, user: CurrentUser, background_tasks: BackgroundTasks
):
    conn = get_conn(request)
    try:
        row = articles.get_by_id(conn, article_id, user.owner)
        if not row:
            return JSONResponse({"error": "Article not found"}, status_code=404)
        if row["status"] in ("summarized", "summarizing"):
            return JSONResponse(
                {"error": f"Article already {row['status']}", "id": article_id, "status": row["status"]},
                status_code=409,
            )
        config = request.app.state.config
    finally:
        conn.close()
    background_tasks.add_task(run_rerun_article, article_id, config)
    return ActionResponse(id=article_id, status="summarizing", message="Summarization started")


@router.post("/articles/{article_id}/summary")
def provide_article_summary(request: Request, article_id: int, user: CurrentUser, body: SummaryBody):
    conn = get_conn(request)
    try:
        row = articles.get_by_id(conn, article_id, user.owner)
        if not row:
            return JSONResponse({"error": "Article not found"}, status_code=404)

        config = request.app.state.config
        safe_title = _safe_filename(row["title"])
        summary_path = config.article_summary_dir / f"{safe_title}_summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(body.summary)

        articles.set_summary(conn, article_id, str(summary_path), body.one_sentence_summary)
        return ActionResponse(id=article_id, status="summarized", message="Summary stored")
    finally:
        conn.close()
