from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from content_agent import db
from content_agent.models import AgentConfig


def create_app(config: AgentConfig) -> FastAPI:
    # Import routes here to avoid circular imports at module level
    from content_agent.web.routes import articles, dashboard, episodes, feed, podcasts, runs, settings

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

    app.include_router(dashboard.router)
    app.include_router(feed.router)
    app.include_router(episodes.router)
    app.include_router(podcasts.router)
    app.include_router(articles.router)
    app.include_router(runs.router)
    app.include_router(settings.router)

    @app.on_event("startup")
    async def seed_feeds():
        conn = db.init_db(config.db_path)
        try:
            for f in (config.podcast_feeds or []):
                db.upsert_podcast_feed(conn, f.name, str(f.url))
            for f in (config.article_feeds or []):
                db.upsert_article_feed(conn, f.name, str(f.url))
            conn.commit()
            # Merge DB task model overrides into config
            db_overrides = db.get_task_model_overrides(conn)
            for task_name, override in db_overrides.items():
                config.task_models[task_name] = override
        finally:
            conn.close()

    return app
