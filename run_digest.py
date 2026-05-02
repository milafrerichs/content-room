"""Entry point for the daily digest Render Cron Job."""

import asyncio
import logging
import sys

import yaml
from dotenv import load_dotenv

from src.content_agent import db
from src.content_agent.delivery import SlackDelivery, resolve_webhook_url
from src.content_agent.digest import DigestGenerator
from src.content_agent.models import AgentConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()


def load_config(path: str = "config.yaml") -> AgentConfig:
    with open(path) as f:
        return AgentConfig(**yaml.safe_load(f))


async def main() -> None:
    config = load_config()
    conn = db._connect(config.database_url)
    try:
        generator = DigestGenerator()
        digest = await generator.build(conn, config)
        webhook_url = resolve_webhook_url(config.digest)
        payload = generator.format_slack_blocks(digest)
        ok = SlackDelivery(webhook_url).send(payload)
        if not ok:
            logger.error("Failed to send daily digest")
            sys.exit(1)
        logger.info("Daily digest sent (%d items)", len(digest.items))
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
