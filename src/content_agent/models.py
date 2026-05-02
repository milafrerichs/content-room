import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, HttpUrl, Field, model_validator


# =============================================================================
# Digest Models
# =============================================================================


class DigestConfig(BaseModel):
    enabled: bool = False
    slack_webhook_url: str = ""


class DigestItem(BaseModel):
    title: str
    feed_name: str
    published_date: str
    one_sentence_summary: str
    item_type: Literal["episode", "article"]


class DailyDigestOutput(BaseModel):
    date: str
    overall_summary: str
    top_items: List[str]
    items: List[DigestItem]


# =============================================================================
# Task Model Configuration
# =============================================================================

TASK_NAMES = [
    "extract_wisdom",
    "summarize_micro",
    "extract_sponsors",
    "extract_insights",
    "extract_recommendations",
    "one_sentence",
    "custom_instructions",
]

TASK_LABELS = {
    "extract_wisdom": "Full Summary (extract_wisdom)",
    "summarize_micro": "Micro Summary",
    "extract_sponsors": "Sponsor Extraction",
    "extract_insights": "Insights Extraction",
    "extract_recommendations": "Recommendations",
    "one_sentence": "One-Sentence Summary",
    "custom_instructions": "Custom Re-summarization",
}


class TaskModelOverride(BaseModel):
    """Per-task LLM override. None fields fall back to global default."""

    provider: Optional[Literal["anthropic", "ollama", "openrouter"]] = None
    model: Optional[str] = None
    ollama_base_url: Optional[str] = None


# =============================================================================
# Article Models
# =============================================================================


class ArticleFeed(BaseModel):
    """RSS feed configuration for articles."""

    name: str
    url: HttpUrl
    category: Optional[str] = None
    auto_summarize: bool = False
    last_processed: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "ArticleFeed":
        return cls(
            name=row["name"],
            url=row["url"],
            category=row.get("category"),
            auto_summarize=bool(row["auto_summarize"]),
        )


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


class OneSentenceSummary(BaseModel):
    """A single-sentence summary of content."""

    summary: str = Field(description="A single sentence (max 20 words) summarizing the content")


class ArticleSummary(BaseModel):
    """Micro summary for articles based on summarize_micro pattern."""

    one_sentence_summary: str = Field(description="20-word summary of the article")
    main_points: list[str] = Field(
        description="3 most important points (max 12 words each)"
    )
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

    summary: str = Field(
        description="A 25-word summary including who is presenting and the content being discussed"
    )
    ideas: Optional[list[str]] = Field(
        default_factory=list,
        description="20-50 surprising, insightful, or interesting ideas (each exactly 16 words)",
    )
    insights: Optional[list[str]] = Field(
        default_factory=list,
        description="10-20 refined, abstracted insights from the best ideas (each exactly 16 words)",
    )
    quotes: Optional[list[str]] = Field(
        default_factory=list,
        description="15-30 surprising, insightful quotes with speaker attribution",
    )
    habits: Optional[list[str]] = Field(
        default_factory=list,
        description="15-30 practical personal habits mentioned (each exactly 16 words)",
    )
    facts: Optional[list[str]] = Field(
        default_factory=list,
        description="15-30 interesting facts about the world mentioned (each exactly 16 words)",
    )
    references: Optional[list[str]] = Field(
        default_factory=list,
        description="All mentions of books, articles, tools, projects, or other sources",
    )
    one_sentence_takeaway: Optional[str] = Field(
        description="The most potent takeaway in exactly 15 words"
    )
    recommendations: Optional[list[str]] = Field(
        default_factory=list,
        description="15-30 actionable recommendations (each exactly 16 words)",
    )

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

    sponsors: Optional[list[str]] = Field(
        description="List of official sponsors with format: 'Name | Description | URL'"
    )

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
    main_points: list[str] = Field(
        description="3 most important points (max 12 words each)"
    )
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

    insights: list[str] = Field(
        description="10 surprising and novel insights (8 words each)"
    )

    def to_markdown(self, episode_title: str, podcast_name: str) -> str:
        md = f"# {podcast_name}: {episode_title}\n\n"
        md += "## INSIGHTS\n\n"
        for insight in self.insights:
            md += f"- {insight}\n"
        return md


class Recommendations(BaseModel):
    """Extracted recommendations based on Fabric's extract_recommendations pattern."""

    recommendations: list[str] = Field(
        description="Up to 20 practical recommendations (max 16 words each)"
    )

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
    category: Optional[str] = None
    auto_summarize: bool = False
    last_processed: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "PodcastFeed":
        return cls(
            name=row["name"],
            url=row["url"],
            category=row.get("category"),
            auto_summarize=bool(row["auto_summarize"]),
        )


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
    article_summary_dir: Path = Field(
        default_factory=lambda: Path("./article_summaries")
    )

    database_url: str = Field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "postgresql://localhost/content_agent"
        )
    )
    whisper_model: str = "base"
    max_episodes_per_day: int = 10
    max_articles_per_day: int = 20
    notifications_enabled: bool = True
    speak_results: bool = False
    show_completion_alert: bool = False
    save_to_notes: bool = False
    notes_folder: str = "Podcast Summaries"

    # LLM configuration
    llm_provider: Literal["anthropic", "ollama", "openrouter"] = "ollama"
    llm_model: str = "llama3.2"  # Used when provider=ollama
    anthropic_model: str = "claude-haiku-4-5"  # Used when provider=anthropic
    openrouter_model: str = "anthropic/claude-haiku-4-5"  # Used when provider=openrouter
    ollama_base_url: str = "http://localhost:11434/v1"

    # Per-task model overrides (optional, falls back to global defaults)
    task_models: Dict[str, TaskModelOverride] = Field(default_factory=dict)

    # Digest configuration
    digest: DigestConfig = Field(default_factory=DigestConfig)

    @property
    def active_model(self) -> str:
        """Return the model name for the active provider."""
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        if self.llm_provider == "openrouter":
            return self.openrouter_model
        return self.llm_model

    def _resolve_model_for_provider(self, provider: str) -> str:
        """Return the default model name for a given provider."""
        if provider == "anthropic":
            return self.anthropic_model
        if provider == "openrouter":
            return self.openrouter_model
        return self.llm_model

    def get_task_model_kwargs(self, task_name: str) -> dict:
        """Return provider/model/ollama_base_url kwargs for a summarization task."""
        override = self.task_models.get(task_name)
        if override is None:
            return {
                "provider": self.llm_provider,
                "model": self.active_model,
                "ollama_base_url": self.ollama_base_url,
            }
        provider = override.provider or self.llm_provider
        model = override.model or self._resolve_model_for_provider(provider)
        base_url = override.ollama_base_url or self.ollama_base_url
        return {"provider": provider, "model": model, "ollama_base_url": base_url}

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
        return self


class ProcessingResult(BaseModel):
    episode: PodcastEpisode
    success: bool
    error_message: Optional[str] = None
    processing_time: float

