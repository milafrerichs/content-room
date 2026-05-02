from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from content_agent import db
from content_agent.models import AgentConfig
from content_agent.queries import feeds
from content_agent.queries import settings as qs


def create_app(config: AgentConfig) -> FastAPI:
    # Import routes here to avoid circular imports at module level
    from content_agent.web.routes import api, articles, dashboard, episodes, feed, podcasts, runs, settings

    app = FastAPI(title="Podcast Agent Dashboard")

    templates_dir = Path(__file__).parent.parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    def markdown_filter(text: str) -> str:
        if not text:
            return ""
        return md_lib.markdown(text, extensions=["extra", "nl2br"])

    templates.env.filters["markdown"] = markdown_filter

    app.state.config = config
    app.state.templates = templates

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    app.include_router(api.router)
    app.include_router(dashboard.router)
    app.include_router(feed.router)
    app.include_router(episodes.router)
    app.include_router(podcasts.router)
    app.include_router(articles.router)
    app.include_router(runs.router)
    app.include_router(settings.router)

    @app.on_event("startup")
    async def startup():
        conn = db.init_db(config.database_url)
        try:
            for f in (config.podcast_feeds or []):
                feeds.upsert_podcast(conn, f.name, str(f.url))
            for f in (config.article_feeds or []):
                feeds.upsert_article(conn, f.name, str(f.url))
            conn.commit()
            db_overrides = qs.get_task_overrides(conn)
            for task_name, override in db_overrides.items():
                config.task_models[task_name] = override
        finally:
            conn.close()

    return app
