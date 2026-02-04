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

from .models import AgentConfig, PodcastEpisode, PodcastFeed, ProcessingResult
from .summarizer import summarize_transcript
from . import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("podcast_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class PodcastAgent(BaseModel):
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
        self.config.summary_dir.mkdir(parents=True, exist_ok=True)

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
            return True

        try:
            self.load_whisper_model()
            logger.info(f"Transcribing: {episode.title}")

            result = self.whisper_model.transcribe(str(episode.local_audio_path))

            with open(transcript_path, "w", encoding="utf-8") as f:
                f.write(result["text"])

            episode.transcript_path = transcript_path
            logger.info(f"Transcribed: {transcript_filename}")
            return True

        except Exception as e:
            logger.error(f"Error transcribing {episode.title}: {str(e)}")
            return False

    async def summarize_episode(self, episode: PodcastEpisode) -> bool:
        """Summarize transcript using pydantic-ai Claude agent"""
        if not episode.transcript_path:
            return False

        summary_filename = f"{episode.transcript_path.stem}_summary.md"
        summary_path = self.config.summary_dir / summary_filename

        if summary_path.exists():
            logger.info(f"Summary already exists: {summary_filename}")
            episode.summary_path = summary_path
            return True

        try:
            logger.info(f"Summarizing: {episode.title}")

            with open(episode.transcript_path, "r", encoding="utf-8") as f:
                transcript_content = f.read()

            summary = await summarize_transcript(transcript_content)
            markdown = summary.to_markdown(episode.title, episode.podcast_name)

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

    async def run_processing(self):
        """Main method to process all feeds"""
        logger.info("Starting podcast processing")

        conn = db.init_db(self.config.db_path)
        run_id = db.start_run(conn)
        episodes_discovered = 0

        # Fetch episodes from all feeds and insert into DB
        for feed in self.config.rss_feeds:
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

        # Process pending episodes from DB
        pending = db.get_pending_episodes(conn)
        results = []

        for row in pending:
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
            results.append(result)

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_time = sum(r.processing_time for r in results)

        db.finish_run(conn, run_id, episodes_discovered, successful, failed)
        conn.close()

        logger.info(
            f"Processing complete: {successful} successful, {failed} failed, {total_time:.2f}s total"
        )

        if self.config.notifications_enabled:
            self.send_notification(
                "Podcast Processing Complete",
                f"{successful} episodes processed, {failed} failed",
                f"Total time: {total_time:.1f}s",
            )

        if self.config.speak_results:
            speech_text = f"Podcast processing complete. {successful} episodes processed successfully."
            if failed > 0:
                speech_text += f" {failed} episodes failed."
            self.speak_text(speech_text)

        if self.config.show_completion_alert:
            self.show_alert(
                f"Processing complete!\n\n"
                f"{successful} episodes processed\n"
                f"{failed} failed\n"
                f"Total time: {total_time:.1f}s"
            )

        return results
