import psycopg2
import psycopg2.extras
from fastapi import Request

from content_agent.models import AgentConfig


def get_conn(request: Request):
    """Open a per-request PostgreSQL connection using config from app state."""
    config: AgentConfig = request.app.state.config
    return psycopg2.connect(config.database_url, cursor_factory=psycopg2.extras.RealDictCursor)
