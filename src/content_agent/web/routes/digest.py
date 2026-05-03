"""HTTP endpoint for triggering the daily digest."""

import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Query, Request

from content_agent import db
from content_agent.delivery import SlackDelivery, resolve_webhook_url
from content_agent.digest import DigestGenerator
from content_agent.models import AgentConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/digest", tags=["digest"])


def _parse_date(date_str: str) -> date:
    if date_str:
        return date.fromisoformat(date_str)
    return date.today() - timedelta(days=1)


def _run_digest_sync(config: AgentConfig, target_date: date) -> None:
    asyncio.run(_run_digest(config, target_date))


async def _run_digest(config: AgentConfig, target_date: date) -> None:
    conn = db._connect(config.database_url)
    try:
        generator = DigestGenerator()
        digest = await generator.build(conn, config, target_date=target_date)
        webhook_url = resolve_webhook_url(config.digest)
        payload = generator.format_slack_blocks(digest)
        ok = SlackDelivery(webhook_url).send(payload)
        if ok:
            logger.info("Daily digest sent for %s (%d items)", target_date, len(digest.items))
        else:
            logger.error("Failed to send daily digest for %s", target_date)
    except Exception:
        logger.exception("Error running daily digest for %s", target_date)
    finally:
        conn.close()


@router.post("/trigger", status_code=202)
async def trigger_digest(
    background_tasks: BackgroundTasks,
    request: Request,
    date_str: str = Query(default="", alias="date"),
) -> dict:
    config: AgentConfig = request.app.state.config
    target_date = _parse_date(date_str)
    background_tasks.add_task(_run_digest_sync, config, target_date)
    return {"status": "accepted", "date": target_date.isoformat()}
