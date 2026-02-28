import sqlite3

from fastapi import Request

from podcast_agent.models import AgentConfig


def get_conn(request: Request) -> sqlite3.Connection:
    """Open a per-request SQLite connection using config from app state."""
    config: AgentConfig = request.app.state.config
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    return conn
