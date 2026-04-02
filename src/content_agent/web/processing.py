import asyncio
import logging
import sqlite3
from pathlib import Path

from content_agent.agent import ContentAgent
from content_agent.models import AgentConfig, Article, PodcastEpisode
from content_agent import db

logger = logging.getLogger(__name__)


async def rerun_episode(episode_id: int, config: AgentConfig) -> None:
    """Run only the needed pipeline step(s) for an episode that needs retrying."""
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            logger.error(f"Episode {episode_id} not found for rerun")
            return

        start_status = row["status"]

        episode = PodcastEpisode(
            title=row["title"],
            description=row["description"],
            audio_url=row["audio_url"],
            published_date=row["published_date"],
            duration=row["duration"],
            podcast_name=row["podcast_name"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)

        if start_status == "transcribed":
            if not await agent.summarize_episode(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to summarize")
                return
            db.update_episode_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

        elif start_status == "downloaded":
            if not await agent.transcribe_episode_async(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to transcribe")
                return
            db.update_episode_status(conn, episode_id, "transcribed", transcript_path=str(episode.transcript_path))

            if not await agent.summarize_episode(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to summarize")
                return
            db.update_episode_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

        else:
            # "discovered" — run the full pipeline
            await agent.process_episode(episode, Path(str(config.db_path)), episode_id)

    except Exception as e:
        logger.error(f"Rerun failed for episode {episode_id}: {e}")
        try:
            db.update_episode_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_rerun_episode(episode_id: int, config: AgentConfig) -> None:
    """Sync wrapper for FastAPI BackgroundTasks (runs in a threadpool thread)."""
    asyncio.run(rerun_episode(episode_id, config))


async def rerun_article(article_id: int, config: AgentConfig) -> None:
    """Re-summarize an article."""
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if row is None:
            logger.error(f"Article {article_id} not found for rerun")
            return

        agent = ContentAgent(config=config)
        article = Article(
            title=row["title"],
            url=row["url"],
            published_date=row["published_date"],
            author=row["author"],
            content=row["content"],
            description=row["description"],
            feed_name=row["feed_name"],
        )
        await agent.process_article(article, Path(str(config.db_path)), article_id)

    except Exception as e:
        logger.error(f"Rerun failed for article {article_id}: {e}")
        try:
            db.update_article_status(conn, article_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_rerun_article(article_id: int, config: AgentConfig) -> None:
    """Sync wrapper for FastAPI BackgroundTasks."""
    asyncio.run(rerun_article(article_id, config))


async def download_single_episode(episode_id: int, config: AgentConfig) -> None:
    """Download + transcribe a single episode by ID (full pipeline from 'discovered')."""
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            logger.error(f"Episode {episode_id} not found for download")
            return

        episode = PodcastEpisode(
            title=row["title"],
            description=row["description"],
            audio_url=row["audio_url"],
            published_date=row["published_date"],
            duration=row["duration"],
            podcast_name=row["podcast_name"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        await agent.process_episode(episode, Path(str(config.db_path)), episode_id)

    except Exception as e:
        logger.error(f"Download failed for episode {episode_id}: {e}")
        try:
            db.update_episode_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_download_single_episode(episode_id: int, config: AgentConfig) -> None:
    """Sync wrapper for FastAPI BackgroundTasks."""
    asyncio.run(download_single_episode(episode_id, config))


async def transcribe_episode(episode_id: int, config: AgentConfig) -> None:
    """Download (if needed) + transcribe a single episode."""
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            logger.error(f"Episode {episode_id} not found for transcription")
            return

        episode = PodcastEpisode(
            title=row["title"],
            description=row["description"],
            audio_url=row["audio_url"],
            published_date=row["published_date"],
            duration=row["duration"],
            podcast_name=row["podcast_name"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        # process_episode does download + transcribe (no summarization)
        await agent.process_episode(episode, Path(str(config.db_path)), episode_id)

    except Exception as e:
        logger.error(f"Transcription failed for episode {episode_id}: {e}")
        try:
            db.update_episode_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_transcribe_episode(episode_id: int, config: AgentConfig) -> None:
    """Sync wrapper for FastAPI BackgroundTasks."""
    asyncio.run(transcribe_episode(episode_id, config))


async def summarize_episode_only(episode_id: int, config: AgentConfig) -> None:
    """Summarize a transcribed episode (does not transcribe)."""
    conn = sqlite3.connect(str(config.db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            logger.error(f"Episode {episode_id} not found for summarization")
            return

        episode = PodcastEpisode(
            title=row["title"],
            description=row["description"],
            audio_url=row["audio_url"],
            published_date=row["published_date"],
            duration=row["duration"],
            podcast_name=row["podcast_name"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        db.update_episode_status(conn, episode_id, "summarizing")
        if not await agent.summarize_episode(episode):
            db.update_episode_status(conn, episode_id, "failed", error_message="Failed to summarize")
            return
        db.update_episode_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

    except Exception as e:
        logger.error(f"Summarization failed for episode {episode_id}: {e}")
        try:
            db.update_episode_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_summarize_episode(episode_id: int, config: AgentConfig) -> None:
    """Sync wrapper for FastAPI BackgroundTasks."""
    asyncio.run(summarize_episode_only(episode_id, config))
