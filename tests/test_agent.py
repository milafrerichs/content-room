import asyncio
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from content_agent import db
from content_agent.agent import ContentAgent
from content_agent.models import (
    Article,
    PodcastEpisode,
    ProcessingResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(**overrides):
    defaults = dict(
        title="Test Episode",
        description="desc",
        audio_url="http://example.com/ep.mp3",
        published_date=datetime(2025, 1, 1),
        podcast_name="TestPod",
    )
    defaults.update(overrides)
    return PodcastEpisode(**defaults)


def _make_article(**overrides):
    defaults = dict(
        title="Test Article",
        url="http://example.com/art.html",
        published_date=datetime(2025, 1, 1),
        content="Some article content here.",
        feed_name="TestFeed",
    )
    defaults.update(overrides)
    return Article(**defaults)


def _make_agent(tmp_config, mock_whisper_model=None):
    agent = ContentAgent(config=tmp_config)
    if mock_whisper_model:
        agent.whisper_model = mock_whisper_model
    return agent


# ---------------------------------------------------------------------------
# Step 1b: Processing status tracking
# ---------------------------------------------------------------------------

class TestProcessingStatuses:
    async def test_process_episode_sets_downloading_status(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        statuses_seen = []

        async def spy_download(self_arg, episode):
            c = db.init_db(tmp_config.db_path)
            row = c.execute("SELECT status FROM episodes WHERE id = ?", (eid,)).fetchone()
            statuses_seen.append(row["status"])
            c.close()
            return False

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", spy_download):
            await agent.process_episode(ep, tmp_config.db_path, eid)
        assert "downloading" in statuses_seen

    async def test_process_episode_sets_transcribing_status(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        statuses_seen = []

        async def fake_download(self_arg, episode):
            episode.local_audio_path = Path("/tmp/fake.mp3")
            return True

        async def spy_transcribe(self_arg, episode):
            c = db.init_db(tmp_config.db_path)
            row = c.execute("SELECT status FROM episodes WHERE id = ?", (eid,)).fetchone()
            statuses_seen.append(row["status"])
            c.close()
            return False

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", fake_download), \
             patch.object(ContentAgent, "transcribe_episode_async", spy_transcribe):
            await agent.process_episode(ep, tmp_config.db_path, eid)
        assert "transcribing" in statuses_seen

    async def test_process_episode_stops_at_transcribed(self, tmp_config, mock_whisper_model):
        """process_episode stops after transcription (summarization is on-demand)."""
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        async def fake_download(self_arg, episode):
            episode.local_audio_path = Path("/tmp/fake.mp3")
            return True

        async def fake_transcribe(self_arg, episode):
            episode.transcript_path = Path("/tmp/fake.txt")
            return True

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", fake_download), \
             patch.object(ContentAgent, "transcribe_episode_async", fake_transcribe):
            result = await agent.process_episode(ep, tmp_config.db_path, eid)

        assert result.success is True
        c = db.init_db(tmp_config.db_path)
        row = c.execute("SELECT status FROM episodes WHERE id = ?", (eid,)).fetchone()
        c.close()
        assert row["status"] == "transcribed"

    async def test_process_article_sets_summarizing_status(self, tmp_config):
        agent = _make_agent(tmp_config)
        conn = db.init_db(tmp_config.db_path)
        db.insert_article(conn, "TestFeed", "art", "http://x.html", "2025-01-01", content="text")
        aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
        conn.close()

        statuses_seen = []

        async def fake_summarize_micro(*args, **kwargs):
            c = db.init_db(tmp_config.db_path)
            row = c.execute("SELECT status FROM articles WHERE id = ?", (aid,)).fetchone()
            statuses_seen.append(row["status"])
            c.close()
            raise Exception("stop")

        with patch("content_agent.agent.summarize_micro", fake_summarize_micro):
            art = _make_article()
            await agent.process_article(art, tmp_config.db_path, aid)

        assert "summarizing" in statuses_seen


# ---------------------------------------------------------------------------
# Step 2: Async Whisper transcription
# ---------------------------------------------------------------------------

class TestAsyncWhisper:
    async def test_transcribe_episode_async_delegates_to_sync(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        called = []

        def spy(self_arg, episode):
            called.append(True)
            return True

        ep = _make_episode(local_audio_path=Path("/tmp/fake.mp3"))
        with patch.object(ContentAgent, "transcribe_episode", spy):
            result = await agent.transcribe_episode_async(ep)
        assert result is True
        assert len(called) == 1

    async def test_transcribe_episode_async_returns_result(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        ep = _make_episode(local_audio_path=Path("/tmp/fake.mp3"))
        with patch.object(ContentAgent, "transcribe_episode", return_value=False):
            result = await agent.transcribe_episode_async(ep)
        assert result is False

    async def test_process_episode_uses_async_transcribe(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        async_called = []

        async def fake_download(self_arg, ep):
            ep.local_audio_path = Path("/tmp/fake.mp3")
            return True

        async def fake_transcribe_async(self_arg, ep):
            async_called.append(True)
            return False

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", fake_download), \
             patch.object(ContentAgent, "transcribe_episode_async", fake_transcribe_async):
            await agent.process_episode(ep, tmp_config.db_path, eid)
        assert len(async_called) == 1


# ---------------------------------------------------------------------------
# Step 3: Semaphores
# ---------------------------------------------------------------------------

class TestSemaphores:
    def test_content_agent_has_semaphores(self, tmp_config):
        agent = _make_agent(tmp_config)
        assert isinstance(agent._whisper_semaphore, asyncio.Semaphore)
        assert isinstance(agent._llm_semaphore, asyncio.Semaphore)
        assert isinstance(agent._download_semaphore, asyncio.Semaphore)

    async def test_whisper_semaphore_limits_concurrency(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        async def tracked_work():
            nonlocal max_concurrent, current
            async with agent._whisper_semaphore:
                async with lock:
                    current += 1
                    max_concurrent = max(max_concurrent, current)
                await asyncio.sleep(0.05)
                async with lock:
                    current -= 1

        await asyncio.gather(*[tracked_work() for _ in range(3)])
        assert max_concurrent == 1

    async def test_llm_semaphore_limits_concurrency(self, tmp_config):
        agent = _make_agent(tmp_config)
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        async def tracked_work():
            nonlocal max_concurrent, current
            async with agent._llm_semaphore:
                async with lock:
                    current += 1
                    max_concurrent = max(max_concurrent, current)
                await asyncio.sleep(0.05)
                async with lock:
                    current -= 1

        await asyncio.gather(*[tracked_work() for _ in range(6)])
        assert max_concurrent <= 3


# ---------------------------------------------------------------------------
# Step 4: Per-task DB connections
# ---------------------------------------------------------------------------

class TestPerTaskDB:
    async def test_process_episode_accepts_db_path(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        async def fake_download(self_arg, ep):
            return False

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", fake_download):
            result = await agent.process_episode(ep, tmp_config.db_path, eid)
        assert result.success is False

    async def test_process_episode_opens_own_connection(self, tmp_config, mock_whisper_model):
        agent = _make_agent(tmp_config, mock_whisper_model)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "TestPod", "ep", "http://x.mp3", "2025-01-01")
        eid = conn.execute("SELECT id FROM episodes").fetchone()["id"]
        conn.close()

        async def fake_download(self_arg, ep):
            return False

        ep = _make_episode()
        with patch.object(ContentAgent, "download_episode", fake_download):
            result = await agent.process_episode(ep, tmp_config.db_path, eid)

        conn2 = db.init_db(tmp_config.db_path)
        row = conn2.execute("SELECT status FROM episodes WHERE id = ?", (eid,)).fetchone()
        assert row["status"] == "failed"
        conn2.close()

    async def test_process_article_accepts_db_path(self, tmp_config):
        agent = _make_agent(tmp_config)
        conn = db.init_db(tmp_config.db_path)
        db.insert_article(conn, "TestFeed", "art", "http://x.html", "2025-01-01", content="text")
        aid = conn.execute("SELECT id FROM articles").fetchone()["id"]
        conn.close()

        with patch("content_agent.agent.summarize_micro", side_effect=Exception("mock")):
            art = _make_article()
            result = await agent.process_article(art, tmp_config.db_path, aid)
            assert result is False

        conn2 = db.init_db(tmp_config.db_path)
        row = conn2.execute("SELECT status FROM articles WHERE id = ?", (aid,)).fetchone()
        assert row["status"] == "failed"
        conn2.close()


# ---------------------------------------------------------------------------
# Step 5: Concurrent batch processing
# ---------------------------------------------------------------------------

class TestConcurrentProcessing:
    async def test_run_processing_processes_episodes_concurrently(self, tmp_config):
        agent = _make_agent(tmp_config)
        conn = db.init_db(tmp_config.db_path)
        for i in range(3):
            db.insert_episode(conn, "Pod", f"ep{i}", f"http://x{i}.mp3", "2025-01-01")
        conn.close()

        call_times = []

        async def fake_process_episode(self_arg, ep, db_path, eid):
            call_times.append(("start", time.monotonic()))
            await asyncio.sleep(0.05)
            call_times.append(("end", time.monotonic()))
            return ProcessingResult(episode=ep, success=True, processing_time=0.05)

        with patch.object(ContentAgent, "process_episode", fake_process_episode), \
             patch("content_agent.agent.db.get_podcast_feeds", return_value=[]), \
             patch("content_agent.agent.db.get_article_feeds", return_value=[]):
            await agent.run_processing()

        # All 3 should have started before any finished (concurrent)
        starts = [t for label, t in call_times if label == "start"]
        ends = [t for label, t in call_times if label == "end"]
        assert len(starts) == 3
        # Last start should be before first end (they overlapped)
        assert starts[-1] < ends[0]

    async def test_run_processing_handles_individual_failures(self, tmp_config):
        agent = _make_agent(tmp_config)
        conn = db.init_db(tmp_config.db_path)
        db.insert_episode(conn, "Pod", "good", "http://good.mp3", "2025-01-01")
        db.insert_episode(conn, "Pod", "bad", "http://bad.mp3", "2025-01-01")
        conn.close()

        call_count = 0

        async def fake_process_episode(self_arg, ep, db_path, eid):
            nonlocal call_count
            call_count += 1
            if ep.title == "bad":
                raise Exception("simulated failure")
            return ProcessingResult(episode=ep, success=True, processing_time=0.01)

        with patch.object(ContentAgent, "process_episode", fake_process_episode), \
             patch("content_agent.agent.db.get_podcast_feeds", return_value=[]), \
             patch("content_agent.agent.db.get_article_feeds", return_value=[]):
            await agent.run_processing()

        assert call_count == 2


# ---------------------------------------------------------------------------
# Step 6: download_podcast concurrent processing
# ---------------------------------------------------------------------------

class TestDownloadPodcastConcurrent:
    async def test_download_podcast_processes_concurrently(self, tmp_config):
        agent = _make_agent(tmp_config)
        conn = db.init_db(tmp_config.db_path)
        db.upsert_podcast_feed(conn, "TestPod", "http://feed.xml")
        conn.commit()
        conn.close()

        episodes = [_make_episode(title=f"ep{i}", audio_url=f"http://x{i}.mp3") for i in range(3)]
        call_count = 0

        async def fake_process_episode(self_arg, ep, db_path, eid):
            nonlocal call_count
            call_count += 1
            return ProcessingResult(episode=ep, success=True, processing_time=0.01)

        with patch.object(ContentAgent, "process_episode", fake_process_episode), \
             patch.object(ContentAgent, "fetch_podcast_episodes", return_value=episodes):
            results = await agent.download_podcast("TestPod", 3)

        assert call_count == 3
