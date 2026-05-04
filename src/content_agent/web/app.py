import os
from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from content_agent import db
from content_agent.models import AgentConfig
from content_agent.queries import settings as qs
from content_agent.web.auth import ClerkJWTVerifier, extract_token

_EXEMPT_PATH_PREFIXES = ("/login", "/logout", "/health", "/webhooks/")


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        token = extract_token(request)
        if not token:
            if request.headers.get("HX-Request"):
                return HTMLResponse(
                    '<div class="text-red-600 text-sm p-2">'
                    'Session expired. <a href="/login" class="underline">Sign in again</a>.'
                    "</div>",
                    status_code=401,
                )
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


def create_app(config: AgentConfig) -> FastAPI:
    from content_agent.web.routes import api, articles, dashboard, episodes, feed, podcasts, runs, settings

    app = FastAPI(title="Podcast Agent Dashboard")

    clerk_jwks_url = os.environ.get("CLERK_JWKS_URL", "")
    clerk_jwt_issuer = os.environ.get("CLERK_JWT_ISSUER", "")
    clerk_publishable_key = os.environ.get("CLERK_PUBLISHABLE_KEY", "")

    app.state.clerk_verifier = ClerkJWTVerifier(clerk_jwks_url, clerk_jwt_issuer) if clerk_jwks_url else None
    app.state.clerk_publishable_key = clerk_publishable_key

    app.add_middleware(_AuthMiddleware)

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

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "clerk_publishable_key": clerk_publishable_key},
        )

    @app.get("/logout", response_class=HTMLResponse)
    async def logout_page(request: Request):
        return templates.TemplateResponse(
            "auth/logout.html",
            {"request": request, "clerk_publishable_key": clerk_publishable_key},
        )

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
            db_overrides = qs.get_task_overrides(conn)
            for task_name, override in db_overrides.items():
                config.task_models[task_name] = override
        finally:
            conn.close()

    return app
