"""Worker entry point for launchd scheduling."""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.content_agent.agent import ContentAgent
from src.content_agent.models import AgentConfig

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("content_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> AgentConfig:
    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)
    return AgentConfig(**raw)


async def main():
    logger.info("Content agent run starting")
    try:
        config = load_config()
        agent = ContentAgent(config=config)
        results = await agent.run_processing()

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        logger.info(f"Run finished: {successful} succeeded, {failed} failed")
    except Exception as e:
        logger.exception(f"Run failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
