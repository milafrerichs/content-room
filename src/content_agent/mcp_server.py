"""MCP server for browsing and interacting with processed podcasts."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastmcp import FastMCP

from . import db
from .models import AgentConfig
from .queries import articles, episodes
from .queries import settings as qs
from .summarizer import (
    extract_insights,
    extract_recommendations,
    extract_sponsors,
    summarize_micro,
    summarize_with_instructions,
)

# Load environment variables
load_dotenv()

# Find project root (where config.yaml lives)
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _load_config() -> AgentConfig:
    """Load config from config.yaml in project root."""
    config_path = _PROJECT_ROOT / "config.yaml"
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)
    return AgentConfig(**raw)


# Initialize MCP server
mcp = FastMCP("content-agent")

# Global config and connection (lazy init)
_config: AgentConfig | None = None
_conn = None


def _get_config() -> AgentConfig:
    global _config
    if _config is None:
        _config = _load_config()
        # Merge DB task model overrides on top of YAML config
        conn = _get_conn()
        db_overrides = qs.get_task_overrides(conn)
        for task_name, override in db_overrides.items():
            _config.task_models[task_name] = override
    return _config


def _get_conn():
    global _conn
    if _conn is None:
        config = _get_config()
        _conn = db.init_db(config.database_url)
    return _conn


def _read_file_content(path: str | None) -> str | None:
    """Read file content, returning None if path is None or file doesn't exist."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _get_summary_preview(summary_path: str | None, max_chars: int = 200) -> str:
    """Extract one-sentence takeaway or summary preview from a summary file."""
    content = _read_file_content(summary_path)
    if not content:
        return ""
    lines = content.split("\n")

    # First try to find ONE-SENTENCE TAKEAWAY (most concise)
    in_takeaway = False
    for line in lines:
        if "ONE-SENTENCE TAKEAWAY" in line.upper():
            in_takeaway = True
            continue
        if in_takeaway and line.strip() and not line.startswith("#"):
            return line.strip()[:max_chars]

    # Fall back to SUMMARY section
    in_summary = False
    for line in lines:
        if line.strip().upper() in ("## SUMMARY", "## Summary"):
            in_summary = True
            continue
        if in_summary and line.strip() and not line.startswith("#"):
            return line.strip()[:max_chars]

    # Last fallback: first 200 chars
    return content[:max_chars].replace("\n", " ")


@mcp.tool()
def list_unread(limit: int = 20) -> list[dict]:
    """List summarized episodes that haven't been reviewed yet.

    Args:
        limit: Maximum number of episodes to return (default 20)

    Returns:
        List of episodes with podcast name, title, date, and summary preview
    """
    conn = _get_conn()
    rows = episodes.get_unread(conn, limit)
    return [
        {
            "id": row["id"],
            "podcast_name": row["podcast_name"],
            "title": row["title"],
            "published_date": row["published_date"],
            "summary_preview": _get_summary_preview(row["summary_path"]),
        }
        for row in rows
    ]


@mcp.tool()
def list_podcasts() -> list[dict]:
    """List all podcast feeds with unread/total episode counts.

    Returns:
        List of podcasts with name, unread count, and total episode count
    """
    conn = _get_conn()
    rows = episodes.get_stats(conn)
    return [
        {
            "podcast_name": row["podcast_name"],
            "unread_count": row["unread_count"],
            "total_episodes": row["total_episodes"],
        }
        for row in rows
    ]


@mcp.tool()
def get_summary(episode_id: int) -> str:
    """Get the full markdown summary for an episode.

    Args:
        episode_id: The episode ID

    Returns:
        Complete markdown summary, or error message if not found
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    content = _read_file_content(row["summary_path"])
    if not content:
        return f"Summary not available for episode {episode_id}"

    return content


@mcp.tool()
def get_transcript(episode_id: int) -> str:
    """Get the full transcript for an episode.

    Args:
        episode_id: The episode ID

    Returns:
        Complete transcript text, or error message if not found
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    content = _read_file_content(row["transcript_path"])
    if not content:
        return f"Transcript not available for episode {episode_id}"

    return content


@mcp.tool()
def mark_read(episode_id: int) -> dict:
    """Mark an episode as reviewed.

    Args:
        episode_id: The episode ID to mark as read

    Returns:
        Confirmation dict with success status
    """
    conn = _get_conn()
    success = episodes.mark_read(conn, episode_id)
    if success:
        return {"success": True, "message": f"Episode {episode_id} marked as read"}
    return {"success": False, "message": f"Episode {episode_id} not found"}


@mcp.tool()
async def resummarize(episode_id: int, instructions: str) -> str:
    """Re-summarize an episode with custom instructions.

    Args:
        episode_id: The episode to resummarize
        instructions: Custom instructions like "focus on actionable health advice"
                      or "extract key quotes" or "summarize in 3 bullet points"

    Returns:
        New summary based on transcript and custom instructions
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    transcript = _read_file_content(row["transcript_path"])
    if not transcript:
        return f"Transcript not available for episode {episode_id}"

    config = _get_config()
    return await summarize_with_instructions(
        transcript,
        instructions,
        **config.get_task_model_kwargs("custom_instructions"),
    )


@mcp.tool()
def search_episodes(query: str, search_in: str = "summaries") -> list[dict]:
    """Search across episode summaries or transcripts.

    Args:
        query: Search term
        search_in: "summaries", "transcripts", or "both"

    Returns:
        Matching episodes with context snippets
    """
    conn = _get_conn()
    query_lower = query.lower()

    # First get candidate episodes from DB (by title/description)
    rows = episodes.search(conn, query, search_in)
    results = []

    for row in rows:
        match_info = {
            "id": row["id"],
            "podcast_name": row["podcast_name"],
            "title": row["title"],
            "published_date": row["published_date"],
            "matches_in": [],
            "context": "",
        }

        # Search in file content
        if search_in in ("summaries", "both"):
            summary = _read_file_content(row["summary_path"])
            if summary and query_lower in summary.lower():
                match_info["matches_in"].append("summary")
                # Extract context around match
                idx = summary.lower().find(query_lower)
                start = max(0, idx - 100)
                end = min(len(summary), idx + len(query) + 100)
                match_info["context"] = "..." + summary[start:end] + "..."

        if search_in in ("transcripts", "both"):
            transcript = _read_file_content(row["transcript_path"])
            if transcript and query_lower in transcript.lower():
                match_info["matches_in"].append("transcript")
                if not match_info["context"]:  # Only if no summary context
                    idx = transcript.lower().find(query_lower)
                    start = max(0, idx - 100)
                    end = min(len(transcript), idx + len(query) + 100)
                    match_info["context"] = "..." + transcript[start:end] + "..."

        # Also check title match
        if query_lower in row["title"].lower():
            match_info["matches_in"].append("title")

        # Only include if there's at least one match
        if match_info["matches_in"]:
            results.append(match_info)

    return results


# =============================================================================
# Article Tools
# =============================================================================


def _get_article_summary_preview(summary_path: str | None, max_chars: int = 200) -> str:
    """Extract summary preview from an article summary file."""
    content = _read_file_content(summary_path)
    if not content:
        return ""
    lines = content.split("\n")

    # Try to find ONE SENTENCE SUMMARY section
    in_summary = False
    for line in lines:
        if "ONE SENTENCE SUMMARY" in line.upper():
            in_summary = True
            continue
        if in_summary and line.strip() and not line.startswith("#"):
            return line.strip()[:max_chars]

    # Fall back to first 200 chars
    return content[:max_chars].replace("\n", " ")


@mcp.tool()
def list_unread_articles(limit: int = 20) -> list[dict]:
    """List summarized articles that haven't been reviewed yet.

    Args:
        limit: Maximum number of articles to return (default 20)

    Returns:
        List of articles with feed name, title, date, author, and summary preview
    """
    conn = _get_conn()
    rows = articles.get_unread(conn, limit)
    return [
        {
            "id": row["id"],
            "feed_name": row["feed_name"],
            "title": row["title"],
            "url": row["url"],
            "published_date": row["published_date"],
            "author": row["author"],
            "summary_preview": _get_article_summary_preview(row["summary_path"]),
        }
        for row in rows
    ]


@mcp.tool()
def list_article_feeds() -> list[dict]:
    """List all article feeds with unread/total article counts.

    Returns:
        List of feeds with name, unread count, and total article count
    """
    conn = _get_conn()
    rows = articles.get_stats(conn)
    return [
        {
            "feed_name": row["feed_name"],
            "unread_count": row["unread_count"],
            "total_articles": row["total_articles"],
        }
        for row in rows
    ]


@mcp.tool()
def get_article_summary(article_id: int) -> str:
    """Get the full markdown summary for an article.

    Args:
        article_id: The article ID

    Returns:
        Complete markdown summary, or error message if not found
    """
    conn = _get_conn()
    row = articles.get_by_id(conn, article_id)
    if not row:
        return f"Article {article_id} not found"

    content = _read_file_content(row["summary_path"])
    if not content:
        return f"Summary not available for article {article_id}"

    return content


@mcp.tool()
def get_article_content(article_id: int) -> str:
    """Get the original article content (from RSS feed).

    Args:
        article_id: The article ID

    Returns:
        Original article content, or error message if not found
    """
    conn = _get_conn()
    row = articles.get_by_id(conn, article_id)
    if not row:
        return f"Article {article_id} not found"

    content = row["content"]
    if not content:
        return f"Content not available for article {article_id}"

    # Include metadata
    result = f"# {row['title']}\n\n"
    if row["author"]:
        result += f"**Author:** {row['author']}\n"
    result += f"**Published:** {row['published_date']}\n"
    result += f"**Source:** {row['url']}\n\n"
    result += "---\n\n"
    result += content

    return result


@mcp.tool()
def mark_article_read(article_id: int) -> dict:
    """Mark an article as reviewed.

    Args:
        article_id: The article ID to mark as read

    Returns:
        Confirmation dict with success status
    """
    conn = _get_conn()
    success = articles.mark_read(conn, article_id)
    if success:
        return {"success": True, "message": f"Article {article_id} marked as read"}
    return {"success": False, "message": f"Article {article_id} not found"}


@mcp.tool()
def search_articles(query: str) -> list[dict]:
    """Search across article titles, descriptions, and content.

    Args:
        query: Search term

    Returns:
        Matching articles with context snippets
    """
    conn = _get_conn()
    query_lower = query.lower()
    rows = articles.search(conn, query)
    results = []

    for row in rows:
        match_info = {
            "id": row["id"],
            "feed_name": row["feed_name"],
            "title": row["title"],
            "url": row["url"],
            "published_date": row["published_date"],
            "author": row["author"],
            "matches_in": [],
            "context": "",
        }

        # Check where the match occurred
        if query_lower in row["title"].lower():
            match_info["matches_in"].append("title")

        content = row["content"] or ""
        if query_lower in content.lower():
            match_info["matches_in"].append("content")
            # Extract context around match
            idx = content.lower().find(query_lower)
            start = max(0, idx - 100)
            end = min(len(content), idx + len(query) + 100)
            match_info["context"] = "..." + content[start:end] + "..."

        # Check summary file for matches
        summary = _read_file_content(row["summary_path"])
        if summary and query_lower in summary.lower():
            match_info["matches_in"].append("summary")
            if not match_info["context"]:
                idx = summary.lower().find(query_lower)
                start = max(0, idx - 100)
                end = min(len(summary), idx + len(query) + 100)
                match_info["context"] = "..." + summary[start:end] + "..."

        if match_info["matches_in"]:
            results.append(match_info)

    return results


@mcp.tool()
async def resummarize_article(article_id: int, instructions: str) -> str:
    """Re-summarize an article with custom instructions.

    Args:
        article_id: The article to resummarize
        instructions: Custom instructions like "focus on key takeaways"
                      or "summarize in 3 bullet points"

    Returns:
        New summary based on article content and custom instructions
    """
    conn = _get_conn()
    row = articles.get_by_id(conn, article_id)
    if not row:
        return f"Article {article_id} not found"

    content = row["content"]
    if not content:
        return f"Content not available for article {article_id}"

    config = _get_config()
    return await summarize_with_instructions(
        content,
        instructions,
        **config.get_task_model_kwargs("custom_instructions"),
    )


# =============================================================================
# Fabric Pattern Tools (Podcasts)
# =============================================================================


@mcp.tool()
async def get_sponsors(episode_id: int) -> str:
    """Extract sponsor information from an episode transcript.

    Run this first to identify advertisement segments before other analysis.

    Args:
        episode_id: The episode ID

    Returns:
        Markdown formatted list of sponsors, or message if none found
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    transcript = _read_file_content(row["transcript_path"])
    if not transcript:
        return f"Transcript not available for episode {episode_id}"

    config = _get_config()
    result = await extract_sponsors(
        transcript,
        **config.get_task_model_kwargs("extract_sponsors"),
    )
    return result.to_markdown()


@mcp.tool()
async def get_micro_summary(episode_id: int) -> str:
    """Get a quick micro summary of an episode.

    Returns a 20-word summary, 3 main points, and 3 takeaways.

    Args:
        episode_id: The episode ID

    Returns:
        Markdown formatted micro summary
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    transcript = _read_file_content(row["transcript_path"])
    if not transcript:
        return f"Transcript not available for episode {episode_id}"

    config = _get_config()
    result = await summarize_micro(
        transcript,
        **config.get_task_model_kwargs("summarize_micro"),
    )
    return result.to_markdown(row["title"], row["podcast_name"])


@mcp.tool()
async def get_insights(episode_id: int) -> str:
    """Extract 10 key insights from an episode (8 words each, Paul Graham style).

    Args:
        episode_id: The episode ID

    Returns:
        Markdown formatted list of insights
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    transcript = _read_file_content(row["transcript_path"])
    if not transcript:
        return f"Transcript not available for episode {episode_id}"

    config = _get_config()
    result = await extract_insights(
        transcript,
        **config.get_task_model_kwargs("extract_insights"),
    )
    return result.to_markdown(row["title"], row["podcast_name"])


@mcp.tool()
async def get_recommendations(episode_id: int) -> str:
    """Extract actionable recommendations from an episode.

    Returns up to 20 practical recommendations (16 words each).

    Args:
        episode_id: The episode ID

    Returns:
        Markdown formatted list of recommendations
    """
    conn = _get_conn()
    row = episodes.get_by_id(conn, episode_id)
    if not row:
        return f"Episode {episode_id} not found"

    transcript = _read_file_content(row["transcript_path"])
    if not transcript:
        return f"Transcript not available for episode {episode_id}"

    config = _get_config()
    result = await extract_recommendations(
        transcript,
        **config.get_task_model_kwargs("extract_recommendations"),
    )
    return result.to_markdown(row["title"], row["podcast_name"])


@mcp.tool()
async def generate_digest(date: str = "") -> str:
    """Generate a daily digest of yesterday's (or a specific date's) feed items.

    Returns a markdown-formatted digest without sending it anywhere.

    Args:
        date: Target date in YYYY-MM-DD format. Defaults to yesterday.

    Returns:
        Markdown formatted daily digest
    """
    from datetime import date as date_type, timedelta
    from .digest import DigestGenerator

    conn = _get_conn()
    config = _get_config()

    if date:
        target_date = date_type.fromisoformat(date)
    else:
        target_date = date_type.today() - timedelta(days=1)

    generator = DigestGenerator()
    digest = await generator.build(conn, config, target_date=target_date)
    return generator.format_markdown(digest)


@mcp.tool()
async def send_digest(date: str = "") -> str:
    """Generate and send the daily digest to Slack.

    Args:
        date: Target date in YYYY-MM-DD format. Defaults to yesterday.

    Returns:
        Success or error message
    """
    from datetime import date as date_type, timedelta
    from .digest import DigestGenerator
    from .delivery import SlackDelivery, resolve_webhook_url

    conn = _get_conn()
    config = _get_config()

    if date:
        target_date = date_type.fromisoformat(date)
    else:
        target_date = date_type.today() - timedelta(days=1)

    try:
        webhook_url = resolve_webhook_url(config.digest)
    except ValueError as e:
        return f"Error: {e}"

    generator = DigestGenerator()
    digest = await generator.build(conn, config, target_date=target_date)
    payload = generator.format_slack_blocks(digest)
    ok = SlackDelivery(webhook_url).send(payload)

    if ok:
        return f"Digest for {target_date} sent to Slack ({len(digest.items)} items)."
    return f"Failed to send digest for {target_date}. Check logs for details."


if __name__ == "__main__":
    mcp.run()
