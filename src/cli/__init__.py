"""
CLI Tool with Click
"""

from pathlib import Path
import asyncio
import click
import yaml
from podcast_agent import __version__, PodcastAgent, AgentConfig, PodcastFeed


@click.group()
def cli():
    """The CLI for the news agent."""
    pass


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


@cli.command(name="run")
@click.option("--schedule", is_flag=True, default=False, help="Run in scheduled mode.")
@click.option("--summarize", is_flag=True, default=False, help="Run summarization only.")
def run(schedule, summarize):
    """Process podcast feeds."""
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


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload.")
@click.option("--config", "config_path", default="config.yaml", show_default=True, help="Path to config file.")
def serve(host, port, reload, config_path):
    """Start the web dashboard."""
    import uvicorn
    from podcast_agent.web.app import create_app

    config = load_config(config_path)
    app = create_app(config)
    click.echo(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)


async def work():
    """Main work entry point"""
    print("🎧 Starting Podcast Agent...")

    config = load_config()
    agent = PodcastAgent(config=config)
    results = await agent.run_daily_processing()

    print("\n📊 Processing Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")

    print("\n🕐 To run daily at 7:00 AM, use: news run --schedule")


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

    config = load_config()
    agent = PodcastAgent(config=config)
    results = await agent.run_summarization_only()

    print("\n📊 Summarization Results:")
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"{status} {result.episode.title} ({result.processing_time:.1f}s)")
        if not result.success:
            print(f"   Error: {result.error_message}")


if __name__ == "__main__":
    cli()
