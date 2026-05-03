import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from content_agent import db
from content_agent.models import AgentConfig

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://content_agent:content_agent@localhost/content_agent",
)


@pytest.fixture
def pg_conn():
    """Open a PostgreSQL connection, initialize schema, and roll back after the test."""
    conn = db.init_db(TEST_DATABASE_URL)
    # Truncate tables so each test starts clean
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE episodes, articles, podcast_feeds, article_feeds, runs, settings RESTART IDENTITY CASCADE")
    conn.commit()
    cur.close()
    yield conn
    conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database (kept for legacy tests)."""
    return tmp_path / "test.db"


@pytest.fixture
def tmp_config(tmp_path):
    """Return an AgentConfig pointing at temporary directories and test PostgreSQL."""
    return AgentConfig(
        podcast_feeds=[],
        article_feeds=[],
        download_dir=tmp_path / "downloads",
        transcript_dir=tmp_path / "transcripts",
        podcast_summary_dir=tmp_path / "summaries",
        article_summary_dir=tmp_path / "article_summaries",
        database_url=TEST_DATABASE_URL,
        whisper_model="base",
        notifications_enabled=False,
        speak_results=False,
        show_completion_alert=False,
    )


@pytest.fixture
def mock_whisper_model():
    """Return a mock Whisper model that returns a fixed transcription."""
    model = MagicMock()
    model.transcribe.return_value = {"text": "This is a test transcription."}
    return model
