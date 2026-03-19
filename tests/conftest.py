import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from content_agent.models import AgentConfig


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database."""
    return tmp_path / "test.db"


@pytest.fixture
def tmp_config(tmp_path):
    """Return an AgentConfig pointing at temporary directories."""
    return AgentConfig(
        podcast_feeds=[],
        article_feeds=[],
        download_dir=tmp_path / "downloads",
        transcript_dir=tmp_path / "transcripts",
        podcast_summary_dir=tmp_path / "summaries",
        article_summary_dir=tmp_path / "article_summaries",
        db_path=tmp_path / "test.db",
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
