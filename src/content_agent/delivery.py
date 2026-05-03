"""Delivery channels for the daily digest."""

import logging
import os

import requests

from .models import DigestConfig

logger = logging.getLogger(__name__)


def resolve_webhook_url(config: DigestConfig) -> str:
    url = config.slack_webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        raise ValueError("SLACK_WEBHOOK_URL is not configured. Set it in config.yaml or as an environment variable.")
    return url


class SlackDelivery:
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(self, payload: dict) -> bool:
        try:
            response = requests.post(self._webhook_url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.error("Slack webhook returned %d: %s", response.status_code, response.text)
                return False
            return True
        except Exception as e:
            logger.error("Failed to send Slack digest: %s", e)
            return False
