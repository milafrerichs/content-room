from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from content_agent import ContentAgent

router = APIRouter(prefix="/podcasts")


@router.get("", response_class=HTMLResponse)
def podcasts_page(request: Request):
    config = request.app.state.config
    templates = request.app.state.templates
    feeds = config.podcast_feeds or []
    return templates.TemplateResponse("podcasts/list.html", {
        "request": request,
        "feeds": feeds,
    })


@router.post("/{podcast_name}/download", response_class=HTMLResponse)
async def download_podcast(request: Request, podcast_name: str, count: int = Form(default=1)):
    config = request.app.state.config
    templates = request.app.state.templates
    agent = ContentAgent(config=config)
    try:
        results = await agent.download_podcast(podcast_name, count)
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        message = f"Done: {successful} succeeded, {failed} failed"
        error = None
    except ValueError as e:
        message = None
        error = str(e)
    return templates.TemplateResponse("podcasts/_download_result.html", {
        "request": request,
        "podcast_name": podcast_name,
        "message": message,
        "error": error,
    })
