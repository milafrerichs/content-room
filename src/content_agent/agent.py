import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
import tempfile
import subprocess

import aiohttp
import feedparser
import whisper
from pydantic import BaseModel, PrivateAttr

from .models import AgentConfig, Article, ArticleFeed, PodcastEpisode, PodcastFeed, ProcessingResult
from .summarizer import extract_sponsors, summarize_micro, summarize_one_sentence, summarize_transcript
from . import db
from .queries import articles, episodes, feeds, runs


def clean_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities from text."""
    import re
    from html import unescape
    text = re.sub(r'<[^>]+>', '', text)
    return unescape(text)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("content_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ContentAgent(BaseModel):
    config: AgentConfig
    whisper_model: Optional[object] = None

    _whisper_semaphore: asyncio.Semaphore = PrivateAttr(default_factory=lambda: asyncio.Semaphore(1))
    _llm_semaphore: asyncio.Semaphore = PrivateAttr(default_factory=lambda: asyncio.Semaphore(3))
    _download_semaphore: asyncio.Semaphore = PrivateAttr(default_factory=lambda: asyncio.Semaphore(3))

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        self._setup_directories()

    def _setup_directories(self):
        """Create necessary directories if they don't exist"""
        self.config.download_dir.mkdir(parents=True, exist_ok=True)
        self.config.transcript_dir.mkdir(parents=True, exist_ok=True)
        self.config.podcast_summary_dir.mkdir(parents=True, exist_ok=True)
        self.config.article_summary_dir.mkdir(parents=True, exist_ok=True)

    def load_whisper_model(self):
        """Load Whisper model for transcription"""
        if not self.whisper_model:
            logger.info(f"Loading Whisper model: {self.config.whisper_model}")
            self.whisper_model = whisper.load_model(self.config.whisper_model)

    def run_applescript(self, script: str) -> str:
        """Run AppleScript command and return result"""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".applescript", delete=False
            ) as f:
                f.write(script)
                script_path = f.name

            cmd = ["osascript", script_path]
            result = subprocess.run(cmd, capture_output=True, text=True)

            import os
            os.unlink(script_path)

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                logger.error(f"AppleScript error: {result.stderr}")
                return ""

        except Exception as e:
            logger.error(f"AppleScript error: {str(e)}")
            return ""

    def send_notification(self, title: str, message: str, subtitle: str = ""):
        """Send macOS notification"""
        script = f'''
        display notification "{message}" with title "{title}" subtitle "{subtitle}"
        '''
        return self.run_applescript(script)

    def show_alert(self, message: str, title: str = "Podcast Agent"):
        """Show macOS alert dialog"""
        script = f'''
        display alert "{title}" message "{message}"
        '''
        return self.run_applescript(script)

    def speak_text(self, text: str):
        """Use macOS text-to-speech"""
        script = f'''
        say "{text}"
        '''
        return self.run_applescript(script)

    def save_to_notes(
        self, title: str, content: str, folder: str = "Podcast Summaries"
    ):
        """Save content to Apple Notes"""
        escaped_content = content.replace('"', '\\"').replace("\\", "\\\\")
        escaped_title = title.replace('"', '\\"').replace("\\", "\\\\")
        escaped_folder = folder.replace('"', '\\"').replace("\\", "\\\\")

        script = f'''
        tell application "Notes"
            activate
            try
                set targetFolder to folder "{escaped_folder}"
            on error
                set targetFolder to make new folder with properties {{name:"{escaped_folder}"}}
            end try
            tell targetFolder
                make new note with properties {{name:"{escaped_title}", body:"{escaped_content}"}}
            end tell
        end tell
        '''
        return self.run_applescript(script)

    def _get_or_create_canonical_feed(self, conn, url: str, feed_type: str) -> int:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO canonical_feeds (url, feed_type) VALUES (%s, %s) ON CONFLICT (url) DO NOTHING",
            (url, feed_type),
        )
        cur.execute("SELECT id FROM canonical_feeds WHERE url = %s", (url,))
        row = cur.fetchone()
        cur.close()
        conn.commit()
        return row["id"]

    async def fetch_rss_feed(self, feed: PodcastFeed) -> List[PodcastEpisode]:
        """Fetch and parse RSS feed to get recent episodes"""
        logger.info(f"Fetching RSS feed: {feed.name}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(feed.url)) as response:
                    content = await response.text()

            parsed_feed = feedparser.parse(content)
            episode_list = []

            today = datetime.now().date()
            yesterday = today - timedelta(days=1)

            for entry in parsed_feed.entries[: self.config.max_episodes_per_day]:
                pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))

                if pub_date.date() not in [today, yesterday]:
                    continue

                audio_url = None
                for link in entry.get("links", []):
                    if link.get("type", "").startswith("audio/"):
                        audio_url = link["href"]
                        break

                if audio_url:
                    episode = PodcastEpisode(
                        title=entry.title,
                        description=entry.get("description", ""),
                        audio_url=audio_url,
                        published_date=pub_date,
                        duration=entry.get("itunes_duration"),
                        podcast_name=feed.name,
                        podcast_feed_id=feed.id,
                    )
                    episode_list.append(episode)

            return episode_list

        except Exception as e:
            logger.error(f"Error fetching RSS feed {feed.name}: {str(e)}")
            return []

    async def download_episode(self, episode: PodcastEpisode) -> bool:
        """Download podcast episode audio file"""
        filename = f"{episode.podcast_name}_{episode.title}".replace(" ", "_").replace(
            "/", "_"
        )
        filename = f"{filename}.mp3"
        audio_path = self.config.download_dir / filename

        if audio_path.exists():
            logger.info(f"Audio file already exists: {filename}")
            episode.local_audio_path = audio_path
            return True

        try:
            logger.info(f"Downloading: {episode.title}")
            async with aiohttp.ClientSession() as session:
                async with session.get(str(episode.audio_url)) as response:
                    if response.status == 200:
                        with open(audio_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)

                        episode.local_audio_path = audio_path
                        logger.info(f"Downloaded: {filename}")
                        return True
                    else:
                        logger.error(
                            f"Failed to download {episode.title}: HTTP {response.status}"
                        )
                        return False

        except Exception as e:
            logger.error(f"Error downloading {episode.title}: {str(e)}")
            return False

    def transcribe_episode(self, episode: PodcastEpisode) -> bool:
        """Transcribe podcast episode using Whisper"""
        if not episode.local_audio_path:
            return False

        transcript_filename = f"{episode.local_audio_path.stem}.txt"
        transcript_path = self.config.transcript_dir / transcript_filename

        if transcript_path.exists():
            logger.info(f"Transcript already exists: {transcript_filename}")
            episode.transcript_path = transcript_path
            # Clean up audio file if it still exists
            if episode.local_audio_path.exists():
                try:
                    episode.local_audio_path.unlink()
                    logger.info(f"Deleted audio file: {episode.local_audio_path.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete audio file: {e}")
            return True

        try:
            self.load_whisper_model()
            logger.info(f"Transcribing: {episode.title}")

            result = self.whisper_model.transcribe(str(episode.local_audio_path))

            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(result["text"])

            episode.transcript_path = transcript_path
            logger.info(f"Transcribed: {transcript_filename}")

            # Delete audio file to save disk space
            try:
                episode.local_audio_path.unlink()
                logger.info(f"Deleted audio file: {episode.local_audio_path.name}")
            except Exception as e:
                logger.warning(f"Failed to delete audio file: {e}")

            return True

        except Exception as e:
            logger.error(f"Error transcribing {episode.title}: {str(e)}")
            return False

    async def transcribe_episode_async(self, episode: PodcastEpisode) -> bool:
        """Run sync Whisper transcription in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self.transcribe_episode, episode)

    async def _generate_one_sentence(self, table: str, item_id: int, content: str) -> None:
        """Generate and store a one-sentence summary for an article or episode."""
        try:
            async with self._llm_semaphore:
                summary = await summarize_one_sentence(
                    content,
                    **self.config.get_task_model_kwargs("one_sentence"),
                )
            s_conn = db.init_db(self.config.database_url)
            try:
                if table == "articles":
                    articles.update_one_sentence(s_conn, item_id, summary)
                else:
                    episodes.update_one_sentence(s_conn, item_id, summary)
            finally:
                s_conn.close()
        except Exception as e:
            logger.error(f"One-sentence summary failed for {table} {item_id}: {e}")

    async def summarize_episode(self, episode: PodcastEpisode) -> bool:
        """Summarize transcript using pydantic-ai Claude agent"""
        if not episode.transcript_path:
            return False

        summary_filename = f"{episode.transcript_path.stem}_summary.md"
        summary_path = self.config.podcast_summary_dir / summary_filename

        if summary_path.exists():
            logger.info(f"Summary already exists: {summary_filename}")
            episode.summary_path = summary_path
            return True

        try:
            logger.info(f"Summarizing: {episode.title}")

            with open(episode.transcript_path, "r", encoding="utf-8") as f:
                transcript_content = f.read()

            logger.info(f"Transcript length: {len(transcript_content)} chars")

            # Extract sponsors first to identify ad segments
            logger.info(f"Extracting sponsors: {episode.title}")
            try:
                sponsors = await extract_sponsors(
                    transcript_content,
                    **self.config.get_task_model_kwargs("extract_sponsors"),
                )
            except Exception as e:
                logger.error(f"extract_sponsors failed: {type(e).__name__}: {e}", exc_info=True)
                raise

            # Full extract_wisdom summarization
            logger.info(f"Running extract_wisdom summarization: {episode.title}")
            try:
                summary = await summarize_transcript(
                    transcript_content,
                    **self.config.get_task_model_kwargs("extract_wisdom"),
                )
            except Exception as e:
                logger.error(f"summarize_transcript failed: {type(e).__name__}: {e}", exc_info=True)
                raise

            # Combine sponsors and summary into final markdown
            markdown = summary.to_markdown(episode.title, episode.podcast_name)
            markdown += "\n" + sponsors.to_markdown()

            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(markdown)

            episode.summary_path = summary_path
            logger.info(f"Summarized: {summary_filename}")

            if self.config.save_to_notes:
                try:
                    notes_title = f"{episode.podcast_name}: {episode.title}"
                    self.save_to_notes(notes_title, markdown, self.config.notes_folder)
                    logger.info(f"Saved to Notes: {notes_title}")
                except Exception as e:
                    logger.error(f"Failed to save to Notes: {str(e)}")

            return True

        except Exception as e:
            logger.error(f"Error summarizing {episode.title}: {type(e).__name__}: {e}", exc_info=True)
            return False

    async def process_episode(
        self, episode: PodcastEpisode, database_url: str, episode_id: int
    ) -> ProcessingResult:
        """Process a single episode: download, transcribe, summarize"""
        start_time = time.time()
        conn = db.init_db(database_url)

        try:
            # Download
            episodes.update_status(conn, episode_id, "downloading")
            async with self._download_semaphore:
                if not await self.download_episode(episode):
                    episodes.update_status(conn, episode_id, "failed", error_message="Failed to download")
                    return ProcessingResult(
                        episode=episode,
                        success=False,
                        error_message="Failed to download episode",
                        processing_time=time.time() - start_time,
                    )
            episodes.update_status(
                conn, episode_id, "downloaded",
                local_audio_path=str(episode.local_audio_path),
            )

            # Transcribe
            episodes.update_status(conn, episode_id, "transcribing")
            async with self._whisper_semaphore:
                if not await self.transcribe_episode_async(episode):
                    episodes.update_status(conn, episode_id, "failed", error_message="Failed to transcribe")
                    return ProcessingResult(
                        episode=episode,
                        success=False,
                        error_message="Failed to transcribe episode",
                        processing_time=time.time() - start_time,
                    )
            episodes.update_status(
                conn, episode_id, "transcribed",
                transcript_path=str(episode.transcript_path),
            )

            return ProcessingResult(
                episode=episode, success=True, processing_time=time.time() - start_time
            )

        except Exception as e:
            episodes.update_status(conn, episode_id, "failed", error_message=str(e))
            return ProcessingResult(
                episode=episode,
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time,
            )
        finally:
            conn.close()

    async def fetch_podcast_episodes(self, feed: PodcastFeed, count: int) -> List[PodcastEpisode]:
        """Fetch the N most recent episodes from an RSS feed, ignoring date filter."""
        logger.info(f"Fetching RSS feed (no date filter): {feed.name}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(feed.url)) as response:
                    content = await response.text()

            parsed_feed = feedparser.parse(content)
            episode_list = []

            for entry in parsed_feed.entries[:count]:
                pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))

                audio_url = None
                for link in entry.get("links", []):
                    if link.get("type", "").startswith("audio/"):
                        audio_url = link["href"]
                        break

                if audio_url:
                    episode = PodcastEpisode(
                        title=entry.title,
                        description=entry.get("description", ""),
                        audio_url=audio_url,
                        published_date=pub_date,
                        duration=entry.get("itunes_duration"),
                        podcast_name=feed.name,
                        podcast_feed_id=feed.id,
                    )
                    episode_list.append(episode)

            return episode_list

        except Exception as e:
            logger.error(f"Error fetching RSS feed {feed.name}: {str(e)}")
            return []

    async def download_podcast(self, podcast_name: str, count: int) -> List[ProcessingResult]:
        """Download and process N recent episodes from a named podcast, bypassing date filter."""
        conn = db.init_db(self.config.database_url)
        podcast_feeds = feeds.get_all_podcasts(conn)
        feed = next(
            (f for f in podcast_feeds if f.name.lower() == podcast_name.lower()),
            None,
        )
        if feed is None:
            conn.close()
            available = ", ".join(f.name for f in podcast_feeds)
            raise ValueError(f"Podcast '{podcast_name}' not found. Available: {available}")

        episode_list = await self.fetch_podcast_episodes(feed, count)
        if not episode_list:
            logger.info(f"No episodes found for {podcast_name}")
            conn.close()
            return []

        for ep in episode_list:
            episodes.insert(
                conn,
                podcast_feed_id=ep.podcast_feed_id,
                title=ep.title,
                audio_url=str(ep.audio_url),
                published_date=ep.published_date.isoformat(),
                duration=ep.duration,
                description=ep.description,
            )

        pending = episodes.get_pending(conn)
        episode_map = {row["audio_url"]: row for row in pending}

        # Generate one-sentence summaries for newly inserted episodes
        summary_tasks = []
        for row in pending:
            if row["one_sentence_summary"] is None and row["description"]:
                summary_tasks.append(
                    self._generate_one_sentence("episodes", row["id"], row["description"])
                )
        conn.close()

        if summary_tasks:
            await asyncio.gather(*summary_tasks, return_exceptions=True)

        tasks = []
        for ep in episode_list:
            row = episode_map.get(str(ep.audio_url))
            if row is None:
                continue
            tasks.append(self.process_episode(ep, self.config.database_url, row["id"]))

        gather_results = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for r in gather_results:
            if isinstance(r, Exception):
                logger.error(f"Episode processing failed: {r}")
            else:
                results.append(r)
        return results

    async def fetch_article_feed(self, feed: ArticleFeed) -> List[Article]:
        """Fetch and parse RSS feed to get recent articles"""
        logger.info(f"Fetching article feed: {feed.name}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(feed.url)) as response:
                    content = await response.text()

            parsed_feed = feedparser.parse(content)
            article_list = []

            today = datetime.now().date()
            yesterday = today - timedelta(days=1)

            for entry in parsed_feed.entries[: self.config.max_articles_per_day]:
                # Parse published date
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime.fromtimestamp(time.mktime(entry.updated_parsed))
                else:
                    # If no date, skip this entry
                    continue

                # Only process recent articles
                if pub_date.date() not in [today, yesterday]:
                    continue

                # Extract content from RSS entry
                article_content = ""
                if hasattr(entry, 'content') and entry.content:
                    article_content = entry.content[0].get('value', '')
                elif hasattr(entry, 'summary'):
                    article_content = entry.summary
                elif hasattr(entry, 'description'):
                    article_content = entry.description

                # Clean HTML from content
                article_content = clean_html(article_content)

                # Skip if no content
                if not article_content.strip():
                    continue

                article = Article(
                    title=entry.title,
                    url=entry.link,
                    published_date=pub_date,
                    author=getattr(entry, 'author', None),
                    content=article_content,
                    description=clean_html(getattr(entry, 'summary', '') or ''),
                    feed_name=feed.name,
                    article_feed_id=feed.id,
                )
                article_list.append(article)

            return article_list

        except Exception as e:
            logger.error(f"Error fetching article feed {feed.name}: {str(e)}")
            return []

    async def process_article(
        self, article: Article, database_url: str, article_id: int
    ) -> bool:
        """Process a single article: summarize and save"""
        conn = db.init_db(database_url)
        try:
            logger.info(f"Summarizing article: {article.title}")
            articles.update_status(conn, article_id, "summarizing")

            # Summarize using micro summary pattern (appropriate for articles)
            async with self._llm_semaphore:
                summary = await summarize_micro(
                    article.content,
                    **self.config.get_task_model_kwargs("summarize_micro"),
                )

            # Generate filename from title
            safe_title = article.title.replace(" ", "_").replace("/", "_")[:50]
            summary_filename = f"{article.feed_name}_{safe_title}.md"
            summary_path = self.config.article_summary_dir / summary_filename

            # Write markdown summary
            markdown = summary.to_markdown(article.title, article.feed_name)
            markdown += f"\n\n---\n\n**Source:** [{article.title}]({article.url})\n"
            if article.author:
                markdown += f"**Author:** {article.author}\n"

            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(markdown)

            articles.update_status(
                conn, article_id, "summarized", summary_path=str(summary_path)
            )
            logger.info(f"Summarized: {summary_filename}")
            return True

        except Exception as e:
            logger.error(f"Error processing article {article.title}: {str(e)}")
            articles.update_status(conn, article_id, "failed", error_message=str(e))
            return False
        finally:
            conn.close()

    async def run_processing(self):
        """Main method to process all feeds (podcasts and articles)"""
        logger.info("Starting content processing")

        conn = db.init_db(self.config.database_url)
        run_id = runs.start(conn)
        episodes_discovered = 0
        articles_discovered = 0

        # Fetch feeds from DB (includes both config and web-UI-added feeds)
        podcast_feeds = feeds.get_all_podcasts(conn)
        article_feeds = feeds.get_all_articles(conn)

        podcast_results = await asyncio.gather(
            *[self.fetch_rss_feed(f) for f in podcast_feeds],
            return_exceptions=True,
        )
        article_results = await asyncio.gather(
            *[self.fetch_article_feed(f) for f in article_feeds],
            return_exceptions=True,
        )

        # Build canonical feed ID cache keyed by (url, feed_type)
        canonical_cache: dict[tuple, int] = {}

        def _canonical_id(url: str, feed_type: str) -> int:
            key = (url, feed_type)
            if key not in canonical_cache:
                canonical_cache[key] = self._get_or_create_canonical_feed(conn, url, feed_type)
            return canonical_cache[key]

        # Insert discovered episodes into DB
        for feed_obj, result in zip(podcast_feeds, podcast_results):
            if isinstance(result, Exception):
                logger.error(f"Feed fetch failed: {result}")
                continue
            cf_id = _canonical_id(str(feed_obj.url), "podcast")
            for ep in result:
                episodes.insert(
                    conn,
                    podcast_feed_id=ep.podcast_feed_id,
                    title=ep.title,
                    audio_url=str(ep.audio_url),
                    published_date=ep.published_date.isoformat(),
                    duration=ep.duration,
                    description=ep.description,
                    canonical_feed_id=cf_id,
                )
                episodes_discovered += 1

        # Insert discovered articles into DB
        for feed_obj, result in zip(article_feeds, article_results):
            if isinstance(result, Exception):
                logger.error(f"Article feed fetch failed: {result}")
                continue
            cf_id = _canonical_id(str(feed_obj.url), "article")
            for art in result:
                articles.insert(
                    conn,
                    article_feed_id=art.article_feed_id,
                    title=art.title,
                    url=str(art.url),
                    published_date=art.published_date.isoformat(),
                    author=art.author,
                    content=art.content,
                    description=art.description,
                    canonical_feed_id=cf_id,
                )
                articles_discovered += 1

        # Generate one-sentence summaries only for feeds with auto_summarize enabled
        one_sentence_tasks = []

        for row in articles.get_needing_one_sentence(conn):
            one_sentence_tasks.append(
                self._generate_one_sentence("articles", row["id"], row["content"])
            )

        for row in episodes.get_needing_one_sentence(conn):
            one_sentence_tasks.append(
                self._generate_one_sentence("episodes", row["id"], row["description"])
            )

        if one_sentence_tasks:
            logger.info(f"Generating one-sentence summaries for {len(one_sentence_tasks)} items")
            await asyncio.gather(*one_sentence_tasks, return_exceptions=True)

        # Finish run record (discovery only — transcription/summarization are on-demand via API)
        runs.finish(
            conn,
            run_id,
            episodes_discovered,
            0,  # episodes_processed
            0,  # episodes_failed
            articles_discovered,
            0,  # articles_processed
            0,  # articles_failed
        )
        conn.close()

        logger.info(
            f"Discovery complete: {episodes_discovered} episodes, "
            f"{articles_discovered} articles discovered"
        )

        if self.config.notifications_enabled:
            self.send_notification(
                "Content Discovery Complete",
                f"{episodes_discovered} episodes, {articles_discovered} articles discovered",
                "",
            )

        if self.config.speak_results:
            self.speak_text(
                f"Content discovery complete. {episodes_discovered} episodes "
                f"and {articles_discovered} articles discovered."
            )

        if self.config.show_completion_alert:
            self.show_alert(
                f"Discovery complete!\n\n"
                f"{episodes_discovered} episodes discovered\n"
                f"{articles_discovered} articles discovered"
            )

        return []
