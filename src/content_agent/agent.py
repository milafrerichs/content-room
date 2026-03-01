import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
import tempfile
import subprocess

import aiohttp
import feedparser
import whisper
from pydantic import BaseModel

from .models import AgentConfig, Article, ArticleFeed, PodcastEpisode, PodcastFeed, ProcessingResult
from .summarizer import extract_sponsors, summarize_micro, summarize_transcript
from . import db


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

    async def fetch_rss_feed(self, feed: PodcastFeed) -> List[PodcastEpisode]:
        """Fetch and parse RSS feed to get recent episodes"""
        logger.info(f"Fetching RSS feed: {feed.name}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(feed.url)) as response:
                    content = await response.text()

            parsed_feed = feedparser.parse(content)
            episodes = []

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
                    )
                    episodes.append(episode)

            return episodes

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

            # Extract sponsors first to identify ad segments
            logger.info(f"Extracting sponsors: {episode.title}")
            sponsors = await extract_sponsors(
                transcript_content,
                provider=self.config.llm_provider,
                model=self.config.active_model,
                ollama_base_url=self.config.ollama_base_url,
            )

            # Full extract_wisdom summarization
            summary = await summarize_transcript(
                transcript_content,
                provider=self.config.llm_provider,
                model=self.config.active_model,
                ollama_base_url=self.config.ollama_base_url,
            )

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
            logger.error(f"Error summarizing {episode.title}: {str(e)}")
            return False

    async def process_episode(
        self, episode: PodcastEpisode, conn: sqlite3.Connection, episode_id: int
    ) -> ProcessingResult:
        """Process a single episode: download, transcribe, summarize"""
        start_time = time.time()

        try:
            # Download
            if not await self.download_episode(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to download")
                return ProcessingResult(
                    episode=episode,
                    success=False,
                    error_message="Failed to download episode",
                    processing_time=time.time() - start_time,
                )
            db.update_episode_status(
                conn, episode_id, "downloaded",
                local_audio_path=str(episode.local_audio_path),
            )

            # Transcribe
            if not self.transcribe_episode(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to transcribe")
                return ProcessingResult(
                    episode=episode,
                    success=False,
                    error_message="Failed to transcribe episode",
                    processing_time=time.time() - start_time,
                )
            db.update_episode_status(
                conn, episode_id, "transcribed",
                transcript_path=str(episode.transcript_path),
            )

            # Summarize
            if not await self.summarize_episode(episode):
                db.update_episode_status(conn, episode_id, "failed", error_message="Failed to summarize")
                return ProcessingResult(
                    episode=episode,
                    success=False,
                    error_message="Failed to summarize episode",
                    processing_time=time.time() - start_time,
                )
            db.update_episode_status(
                conn, episode_id, "summarized",
                summary_path=str(episode.summary_path),
            )

            return ProcessingResult(
                episode=episode, success=True, processing_time=time.time() - start_time
            )

        except Exception as e:
            db.update_episode_status(conn, episode_id, "failed", error_message=str(e))
            return ProcessingResult(
                episode=episode,
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time,
            )

    async def fetch_article_feed(self, feed: ArticleFeed) -> List[Article]:
        """Fetch and parse RSS feed to get recent articles"""
        logger.info(f"Fetching article feed: {feed.name}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(feed.url)) as response:
                    content = await response.text()

            parsed_feed = feedparser.parse(content)
            articles = []

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
                )
                articles.append(article)

            return articles

        except Exception as e:
            logger.error(f"Error fetching article feed {feed.name}: {str(e)}")
            return []

    async def process_article(
        self, article: Article, conn: sqlite3.Connection, article_id: int
    ) -> bool:
        """Process a single article: summarize and save"""
        try:
            logger.info(f"Summarizing article: {article.title}")

            # Summarize using micro summary pattern (appropriate for articles)
            summary = await summarize_micro(
                article.content,
                provider=self.config.llm_provider,
                model=self.config.active_model,
                ollama_base_url=self.config.ollama_base_url,
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

            db.update_article_status(
                conn, article_id, "summarized", summary_path=str(summary_path)
            )
            logger.info(f"Summarized: {summary_filename}")
            return True

        except Exception as e:
            logger.error(f"Error processing article {article.title}: {str(e)}")
            db.update_article_status(conn, article_id, "failed", error_message=str(e))
            return False

    async def run_processing(self):
        """Main method to process all feeds (podcasts and articles)"""
        logger.info("Starting content processing")

        conn = db.init_db(self.config.db_path)
        run_id = db.start_run(conn)
        episodes_discovered = 0
        articles_discovered = 0

        # Fetch episodes from all podcast feeds and insert into DB
        for feed in self.config.podcast_feeds:
            episodes = await self.fetch_rss_feed(feed)
            for ep in episodes:
                db.insert_episode(
                    conn,
                    podcast_name=ep.podcast_name,
                    title=ep.title,
                    audio_url=str(ep.audio_url),
                    published_date=ep.published_date.isoformat(),
                    duration=ep.duration,
                    description=ep.description,
                )
                episodes_discovered += 1

        # Fetch articles from all article feeds and insert into DB
        for feed in self.config.article_feeds:
            articles = await self.fetch_article_feed(feed)
            for art in articles:
                db.insert_article(
                    conn,
                    feed_name=art.feed_name,
                    title=art.title,
                    url=str(art.url),
                    published_date=art.published_date.isoformat(),
                    author=art.author,
                    content=art.content,
                    description=art.description,
                )
                articles_discovered += 1

        # Process pending episodes from DB
        pending_episodes = db.get_pending_episodes(conn)
        episode_results = []

        for row in pending_episodes:
            episode = PodcastEpisode(
                title=row["title"],
                description=row["description"],
                audio_url=row["audio_url"],
                published_date=datetime.fromisoformat(row["published_date"]),
                duration=row["duration"],
                podcast_name=row["podcast_name"],
                local_audio_path=Path(row["local_audio_path"]) if row["local_audio_path"] else None,
                transcript_path=Path(row["transcript_path"]) if row["transcript_path"] else None,
            )
            result = await self.process_episode(episode, conn, row["id"])
            episode_results.append(result)

        # Process pending articles from DB
        pending_articles = db.get_pending_articles(conn)
        articles_processed = 0
        articles_failed = 0

        for row in pending_articles:
            article = Article(
                title=row["title"],
                url=row["url"],
                published_date=datetime.fromisoformat(row["published_date"]),
                author=row["author"],
                content=row["content"] or "",
                description=row["description"],
                feed_name=row["feed_name"],
            )
            success = await self.process_article(article, conn, row["id"])
            if success:
                articles_processed += 1
            else:
                articles_failed += 1

        episodes_successful = sum(1 for r in episode_results if r.success)
        episodes_failed = len(episode_results) - episodes_successful
        total_time = sum(r.processing_time for r in episode_results)

        db.finish_run(
            conn,
            run_id,
            episodes_discovered,
            episodes_successful,
            episodes_failed,
            articles_discovered,
            articles_processed,
            articles_failed,
        )
        conn.close()

        logger.info(
            f"Processing complete: {episodes_successful} episodes, {articles_processed} articles successful; "
            f"{episodes_failed} episodes, {articles_failed} articles failed"
        )

        if self.config.notifications_enabled:
            self.send_notification(
                "Content Processing Complete",
                f"{episodes_successful} episodes, {articles_processed} articles processed",
                f"Failed: {episodes_failed} episodes, {articles_failed} articles",
            )

        if self.config.speak_results:
            speech_text = f"Content processing complete. {episodes_successful} episodes and {articles_processed} articles processed."
            if episodes_failed > 0 or articles_failed > 0:
                speech_text += f" {episodes_failed + articles_failed} items failed."
            self.speak_text(speech_text)

        if self.config.show_completion_alert:
            self.show_alert(
                f"Processing complete!\n\n"
                f"{episodes_successful} episodes processed\n"
                f"{articles_processed} articles processed\n"
                f"Failed: {episodes_failed} episodes, {articles_failed} articles\n"
                f"Total time: {total_time:.1f}s"
            )

        return episode_results
