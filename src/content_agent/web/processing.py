import asyncio
import logging
from pathlib import Path

import psycopg2
import psycopg2.extras

from content_agent.agent import ContentAgent
from content_agent.models import AgentConfig, Article, PodcastEpisode
from content_agent.queries import articles, episodes

logger = logging.getLogger(__name__)


def _connect(config: AgentConfig):
    return psycopg2.connect(config.database_url, cursor_factory=psycopg2.extras.RealDictCursor)


async def rerun_episode(episode_id: int, config: AgentConfig) -> None:
    conn = _connect(config)
    try:
        row = episodes.get_by_id_internal(conn, episode_id)
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
            podcast_feed_id=row["podcast_feed_id"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)

        if start_status == "transcribed":
            if not await agent.summarize_episode(episode):
                episodes.update_status(conn, episode_id, "failed", error_message="Failed to summarize")
                return
            episodes.update_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

        elif start_status == "downloaded":
            if not await agent.transcribe_episode_async(episode):
                episodes.update_status(conn, episode_id, "failed", error_message="Failed to transcribe")
                return
            episodes.update_status(conn, episode_id, "transcribed", transcript_path=str(episode.transcript_path))

            if not await agent.summarize_episode(episode):
                episodes.update_status(conn, episode_id, "failed", error_message="Failed to summarize")
                return
            episodes.update_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

        else:
            await agent.process_episode(episode, config.database_url, episode_id)

    except Exception as e:
        logger.error(f"Rerun failed for episode {episode_id}: {e}")
        try:
            episodes.update_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_rerun_episode(episode_id: int, config: AgentConfig) -> None:
    asyncio.run(rerun_episode(episode_id, config))


async def rerun_article(article_id: int, config: AgentConfig) -> None:
    conn = _connect(config)
    try:
        row = articles.get_by_id_internal(conn, article_id)
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
            article_feed_id=row["article_feed_id"],
        )
        await agent.process_article(article, config.database_url, article_id)

    except Exception as e:
        logger.error(f"Rerun failed for article {article_id}: {e}")
        try:
            articles.update_status(conn, article_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_rerun_article(article_id: int, config: AgentConfig) -> None:
    asyncio.run(rerun_article(article_id, config))


async def download_single_episode(episode_id: int, config: AgentConfig) -> None:
    conn = _connect(config)
    try:
        row = episodes.get_by_id_internal(conn, episode_id)
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
            podcast_feed_id=row["podcast_feed_id"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        await agent.process_episode(episode, config.database_url, episode_id)

    except Exception as e:
        logger.error(f"Download failed for episode {episode_id}: {e}")
        try:
            episodes.update_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_download_single_episode(episode_id: int, config: AgentConfig) -> None:
    asyncio.run(download_single_episode(episode_id, config))


async def transcribe_episode(episode_id: int, config: AgentConfig) -> None:
    conn = _connect(config)
    try:
        row = episodes.get_by_id_internal(conn, episode_id)
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
            podcast_feed_id=row["podcast_feed_id"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        await agent.process_episode(episode, config.database_url, episode_id)

    except Exception as e:
        logger.error(f"Transcription failed for episode {episode_id}: {e}")
        try:
            episodes.update_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_transcribe_episode(episode_id: int, config: AgentConfig) -> None:
    asyncio.run(transcribe_episode(episode_id, config))


async def summarize_episode_only(episode_id: int, config: AgentConfig) -> None:
    conn = _connect(config)
    try:
        row = episodes.get_by_id_internal(conn, episode_id)
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
            podcast_feed_id=row["podcast_feed_id"],
            local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
            transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            summary_path=Path(row["summary_path"]) if row["summary_path"] else None,
        )

        agent = ContentAgent(config=config)
        episodes.update_status(conn, episode_id, "summarizing")
        if not await agent.summarize_episode(episode):
            episodes.update_status(conn, episode_id, "failed", error_message="Failed to summarize")
            return
        episodes.update_status(conn, episode_id, "summarized", summary_path=str(episode.summary_path))

    except Exception as e:
        logger.error(f"Summarization failed for episode {episode_id}: {e}")
        try:
            episodes.update_status(conn, episode_id, "failed", error_message=str(e))
        except Exception:
            pass
    finally:
        conn.close()


def run_summarize_episode(episode_id: int, config: AgentConfig) -> None:
    asyncio.run(summarize_episode_only(episode_id, config))
