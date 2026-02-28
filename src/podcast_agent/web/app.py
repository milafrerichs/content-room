from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from podcast_agent.models import AgentConfig


def create_app(config: AgentConfig) -> FastAPI:
    # Import routes here to avoid circular imports at module level
    from podcast_agent.web.routes import dashboard, episodes, runs

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
    app.include_router(episodes.router)
    app.include_router(runs.router)

    return app
