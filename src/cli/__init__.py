"""
CLI Tool with Click
"""

import asyncio
import click
import yaml
from dotenv import load_dotenv
from content_agent import __version__, ContentAgent, AgentConfig

load_dotenv()


@click.group()
def cli():
    """The CLI for the content agent."""
    pass


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    """Load configuration from YAML file"""
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)
    return AgentConfig(**raw)


@cli.command(name="run")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def run(config_path):
    """Process podcast and article feeds."""
    click.echo(f"Content Agent {__version__}")
    asyncio.run(work(config_path))


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload.")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def serve(host, port, reload, config_path):
    """Start the web dashboard."""
    import uvicorn
    from content_agent.web.app import create_app

    config = load_config(config_path)
    app = create_app(config)
    click.echo(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)


@cli.command(name="download")
@click.option("--podcast", required=True, help="Podcast name (as in config).")
@click.option("--count", default=1, show_default=True, type=int, help="Number of episodes to download.")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def download(podcast, count, config_path):
    """Download and process N recent episodes from a podcast."""
    config = load_config(config_path)
    agent = ContentAgent(config=config)
    try:
        results = asyncio.run(agent.download_podcast(podcast, count))
    except ValueError as e:
        raise click.UsageError(str(e))
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    click.echo(f"Done: {successful} succeeded, {failed} failed")


@cli.command(name="digest")
@click.option("--date", "date_str", default="", show_default=False, help="Date YYYY-MM-DD (default: yesterday).")
@click.option("--send", "do_send", is_flag=True, default=False, help="Send to Slack instead of printing.")
@click.option("--config", "config_path", default="config.yaml", show_default=True)
def digest(date_str, do_send, config_path):
    """Generate the daily digest and optionally send it to Slack."""
    asyncio.run(_digest(date_str, do_send, config_path))


async def _digest(date_str: str, do_send: bool, config_path: str) -> None:
    from datetime import date, timedelta
    from content_agent import db
    from content_agent.digest import DigestGenerator
    from content_agent.delivery import SlackDelivery, resolve_webhook_url

    config = load_config(config_path)
    conn = db._connect(config.database_url)

    target_date = date.fromisoformat(date_str) if date_str else date.today() - timedelta(days=1)

    try:
        generator = DigestGenerator()
        d = await generator.build(conn, config, target_date=target_date)

        if do_send:
            try:
                webhook_url = resolve_webhook_url(config.digest)
            except ValueError as e:
                raise click.UsageError(str(e))
            payload = generator.format_slack_blocks(d)
            ok = SlackDelivery(webhook_url).send(payload)
            if ok:
                click.echo(f"Digest for {target_date} sent to Slack ({len(d.items)} items).")
            else:
                click.echo("Failed to send digest. Check logs.", err=True)
        else:
            click.echo(generator.format_markdown(d))
    finally:
        conn.close()


async def work(config_path: str = "config.yaml"):
    config = load_config(config_path)
    agent = ContentAgent(config=config)
    results = await agent.run_processing()

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    click.echo(f"Done: {successful} succeeded, {failed} failed")


if __name__ == "__main__":
    cli()
