"""
CLI Tool with Click
"""

from pathlib import Path
import asyncio
import click
import yaml
from podcast_agent import __version__, PodcastAgent, AgentConfig, PodcastFeed


@click.command()
@click.option("--schedule", default=False, help="Number of greetings.")
@click.option("--summarize", default=False, help="The person to greet.")
def cli(schedule, summarize):
    """
    The CLI for the news agent
    """
    click.echo(f"News Agent {__version__}")
    if schedule:
        click.echo("Run schedule")
        schedule_mode()

    elif summarize:
        click.echo("Run summarization")
        asyncio.run(summarize_mode())
    else:
        click.echo("Run once")
        asyncio.run(work())


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    """Load configuration from YAML file"""
    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)

    # Convert feed data to PodcastFeed objects
    feeds = [PodcastFeed(**feed) for feed in config_data["rss_feeds"]]

    # Create AgentConfig
    return AgentConfig(
        rss_feeds=feeds,
        download_dir=Path(config_data["download_dir"]),
        transcript_dir=Path(config_data["transcript_dir"]),
        summary_dir=Path(config_data["summary_dir"]),
        max_episodes_per_day=config_data["max_episodes_per_day"],
        fabric_pattern=config_data["fabric_pattern"],
        mcp_endpoint=config_data.get("mcp_endpoint"),
    )


async def work():
    """Main work entry point"""
    print("🎧 Starting Podcast Agent...")

    # Load configuration
    config = load_config()

    # Create agent
    agent = PodcastAgent(config=config)

    # Run once immediately for testing
    results = await agent.run_daily_processing()

    print("\n📊 Processing Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")

    print("\n🕐 To run daily at 7:00 AM, use: python main.py --schedule")


def schedule_mode():
    """Run in scheduled mode"""
    config = load_config()
    agent = PodcastAgent(config=config)

    print("🎧 Podcast Agent scheduled for daily runs at 7:00 AM")
    print("Press Ctrl+C to stop")

    try:
        agent.schedule_daily_run("07:00")
    except KeyboardInterrupt:
        print("\n👋 Stopping Podcast Agent")


async def summarize_mode():
    """Run summarization only on existing transcripts"""
    print("📝 Starting summarization of existing transcripts...")

    # Load configuration
    config = load_config()

    # Create agent
    agent = PodcastAgent(config=config)

    # Run summarization only
    results = await agent.run_summarization_only()

    print("\n📊 Summarization Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")


if __name__ == "__main__":
    cli(False, False)
