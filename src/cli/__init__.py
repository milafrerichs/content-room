"""
CLI Tool with Click
"""

import asyncio
import click
import yaml
from content_agent import __version__, ContentAgent, AgentConfig


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


async def work(config_path: str = "config.yaml"):
    config = load_config(config_path)
    agent = ContentAgent(config=config)
    results = await agent.run_processing()

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful
    click.echo(f"Done: {successful} succeeded, {failed} failed")


if __name__ == "__main__":
    cli()
