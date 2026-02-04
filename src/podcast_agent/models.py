from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, HttpUrl, Field, model_validator


class PodcastSummary(BaseModel):
    one_sentence_summary: str
    main_points: list[str]  # 5-10 items
    takeaways: list[str]  # 3-5 items
    topics: list[str]  # 3-5 tags

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"
        md += f"## Summary\n\n{self.one_sentence_summary}\n\n"
        md += "## Main Points\n\n"
        for point in self.main_points:
            md += f"- {point}\n"
        md += "\n## Takeaways\n\n"
        for takeaway in self.takeaways:
            md += f"- {takeaway}\n"
        md += "\n## Topics\n\n"
        md += ", ".join(self.topics) + "\n"
        return md


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
    db_path: Path = Field(default_factory=lambda: Path("./podcast_agent.db"))
    whisper_model: str = "base"
    max_episodes_per_day: int = 10
    notifications_enabled: bool = True
    speak_results: bool = False
    show_completion_alert: bool = False
    save_to_notes: bool = False
    notes_folder: str = "Podcast Summaries"

    @model_validator(mode="after")
    def expand_paths(self) -> "AgentConfig":
        self.download_dir = self.download_dir.expanduser()
        self.transcript_dir = self.transcript_dir.expanduser()
        self.summary_dir = self.summary_dir.expanduser()
        self.db_path = self.db_path.expanduser()
        return self


class ProcessingResult(BaseModel):
    episode: PodcastEpisode
    success: bool
    error_message: Optional[str] = None
    processing_time: float