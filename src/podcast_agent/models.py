from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, HttpUrl, Field


class PodcastEpisode(BaseModel):
    title: str
    description: Optional[str] = None
    audio_url: HttpUrl
    published_date: datetime
    duration: Optional[str] = None
    podcast_name: str
    local_audio_path: Optional[Path] = None
    transcript_path: Optional[Path] = None
    summary_path: Optional[Path] = None


class PodcastFeed(BaseModel):
    name: str
    url: HttpUrl
    last_processed: Optional[datetime] = None


class AgentConfig(BaseModel):
    rss_feeds: List[PodcastFeed]
    download_dir: Path = Field(default_factory=lambda: Path("./downloads"))
    transcript_dir: Path = Field(default_factory=lambda: Path("./transcripts"))
    summary_dir: Path = Field(default_factory=lambda: Path("./summaries"))
    max_episodes_per_day: int = 10
    fabric_pattern: str = "summarize"
    mcp_endpoint: Optional[str] = None
    notifications_enabled: bool = True
    speak_results: bool = False
    show_completion_alert: bool = False
    save_to_notes: bool = False
    notes_folder: str = "Podcast Summaries"


class ProcessingResult(BaseModel):
    episode: PodcastEpisode
    success: bool
    error_message: Optional[str] = None
    processing_time: float