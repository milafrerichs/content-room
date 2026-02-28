from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, HttpUrl, Field, model_validator


# =============================================================================
# Article Models
# =============================================================================


class ArticleFeed(BaseModel):
    """RSS feed configuration for articles."""

    name: str
    url: HttpUrl
    last_processed: Optional[datetime] = None


class Article(BaseModel):
    """An article from an RSS feed."""

    title: str
    url: HttpUrl
    published_date: datetime
    author: Optional[str] = None
    content: str
    description: Optional[str] = None
    feed_name: str
    summary_path: Optional[Path] = None


class ArticleSummary(BaseModel):
    """Micro summary for articles based on summarize_micro pattern."""

    one_sentence_summary: str = Field(description="20-word summary of the article")
    main_points: list[str] = Field(description="3 most important points (max 12 words each)")
    takeaways: list[str] = Field(description="3 best takeaways (max 12 words each)")

    def to_markdown(self, article_title: str, feed_name: str) -> str:
        md = f"# {feed_name}: {article_title}\n\n"
        md += "## ONE SENTENCE SUMMARY\n\n"
        md += f"{self.one_sentence_summary}\n\n"
        md += "## MAIN POINTS\n\n"
        for point in self.main_points:
            md += f"- {point}\n"
        md += "\n## TAKEAWAYS\n\n"
        for takeaway in self.takeaways:
            md += f"- {takeaway}\n"
        return md


# =============================================================================
# Podcast Models
# =============================================================================


class PodcastSummary(BaseModel):
    """Structured podcast summary based on Fabric's extract_wisdom pattern."""

    summary: str = Field(description="A 25-word summary including who is presenting and the content being discussed")
    ideas: list[str] = Field(description="20-50 surprising, insightful, or interesting ideas (each exactly 16 words)")
    insights: list[str] = Field(description="10-20 refined, abstracted insights from the best ideas (each exactly 16 words)")
    quotes: list[str] = Field(description="15-30 surprising, insightful quotes with speaker attribution")
    habits: list[str] = Field(description="15-30 practical personal habits mentioned (each exactly 16 words)")
    facts: list[str] = Field(description="15-30 interesting facts about the world mentioned (each exactly 16 words)")
    references: list[str] = Field(description="All mentions of books, articles, tools, projects, or other sources")
    one_sentence_takeaway: str = Field(description="The most potent takeaway in exactly 15 words")
    recommendations: list[str] = Field(description="15-30 actionable recommendations (each exactly 16 words)")

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"

        md += "## SUMMARY\n\n"
        md += f"{self.summary}\n\n"

        md += "## ONE-SENTENCE TAKEAWAY\n\n"
        md += f"{self.one_sentence_takeaway}\n\n"

        md += "## IDEAS\n\n"
        for idea in self.ideas:
            md += f"- {idea}\n"

        md += "\n## INSIGHTS\n\n"
        for insight in self.insights:
            md += f"- {insight}\n"

        md += "\n## QUOTES\n\n"
        for quote in self.quotes:
            md += f"- {quote}\n"

        md += "\n## HABITS\n\n"
        for habit in self.habits:
            md += f"- {habit}\n"

        md += "\n## FACTS\n\n"
        for fact in self.facts:
            md += f"- {fact}\n"

        md += "\n## REFERENCES\n\n"
        for ref in self.references:
            md += f"- {ref}\n"

        md += "\n## RECOMMENDATIONS\n\n"
        for rec in self.recommendations:
            md += f"- {rec}\n"

        return md


class SponsorInfo(BaseModel):
    """Extracted sponsor information from a podcast."""

    sponsors: list[str] = Field(description="List of official sponsors with format: 'Name | Description | URL'")

    def to_markdown(self) -> str:
        if not self.sponsors:
            return "## SPONSORS\n\nNo sponsors identified.\n"
        md = "## SPONSORS\n\n"
        for sponsor in self.sponsors:
            md += f"- {sponsor}\n"
        return md


class MicroSummary(BaseModel):
    """Quick micro summary based on Fabric's summarize_micro pattern."""

    one_sentence_summary: str = Field(description="20-word summary of the content")
    main_points: list[str] = Field(description="3 most important points (max 12 words each)")
    takeaways: list[str] = Field(description="3 best takeaways (max 12 words each)")

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"
        md += "## ONE SENTENCE SUMMARY\n\n"
        md += f"{self.one_sentence_summary}\n\n"
        md += "## MAIN POINTS\n\n"
        for point in self.main_points:
            md += f"- {point}\n"
        md += "\n## TAKEAWAYS\n\n"
        for takeaway in self.takeaways:
            md += f"- {takeaway}\n"
        return md


class Insights(BaseModel):
    """Extracted insights based on Fabric's extract_insights pattern."""

    insights: list[str] = Field(description="10 surprising and novel insights (8 words each)")

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"
        md += "## INSIGHTS\n\n"
        for insight in self.insights:
            md += f"- {insight}\n"
        return md


class Recommendations(BaseModel):
    """Extracted recommendations based on Fabric's extract_recommendations pattern."""

    recommendations: list[str] = Field(description="Up to 20 practical recommendations (max 16 words each)")

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"
        md += "## RECOMMENDATIONS\n\n"
        for rec in self.recommendations:
            md += f"- {rec}\n"
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
    # Podcast feeds (supports legacy rss_feeds or podcast_feeds)
    rss_feeds: Optional[List[PodcastFeed]] = None
    podcast_feeds: Optional[List[PodcastFeed]] = None

    # Article feeds (new)
    article_feeds: List[ArticleFeed] = Field(default_factory=list)

    # Podcast directories
    download_dir: Path = Field(default_factory=lambda: Path("./downloads"))
    transcript_dir: Path = Field(default_factory=lambda: Path("./transcripts"))
    summary_dir: Optional[Path] = None  # Legacy, maps to podcast_summary_dir
    podcast_summary_dir: Path = Field(default_factory=lambda: Path("./summaries"))

    # Article directories
    article_summary_dir: Path = Field(default_factory=lambda: Path("./article_summaries"))

    db_path: Path = Field(default_factory=lambda: Path("./podcast_agent.db"))
    whisper_model: str = "base"
    max_episodes_per_day: int = 10
    max_articles_per_day: int = 20
    notifications_enabled: bool = True
    speak_results: bool = False
    show_completion_alert: bool = False
    save_to_notes: bool = False
    notes_folder: str = "Podcast Summaries"

    # LLM configuration
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-haiku-4-5"  # For anthropic: claude-haiku-4-5, for ollama: llama3.2, etc.
    ollama_base_url: str = "http://localhost:11434/v1"

    @model_validator(mode="after")
    def normalize_config(self) -> "AgentConfig":
        # Handle legacy rss_feeds -> podcast_feeds mapping
        if self.podcast_feeds is None and self.rss_feeds is not None:
            self.podcast_feeds = self.rss_feeds
        elif self.podcast_feeds is None:
            self.podcast_feeds = []

        # Handle legacy summary_dir -> podcast_summary_dir mapping
        if self.summary_dir is not None:
            self.podcast_summary_dir = self.summary_dir

        # Expand all paths
        self.download_dir = self.download_dir.expanduser()
        self.transcript_dir = self.transcript_dir.expanduser()
        self.podcast_summary_dir = self.podcast_summary_dir.expanduser()
        self.article_summary_dir = self.article_summary_dir.expanduser()
        self.db_path = self.db_path.expanduser()
        return self


class ProcessingResult(BaseModel):
    episode: PodcastEpisode
    success: bool
    error_message: Optional[str] = None
    processing_time: float