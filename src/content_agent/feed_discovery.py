"""Discover RSS/Atom feed URLs from any web address."""

import logging
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

import feedparser
import requests

logger = logging.getLogger(__name__)

_FEED_TYPES = {"application/rss+xml", "application/atom+xml"}
_COMMON_PATHS = ["/feed", "/rss", "/atom.xml", "/feed.xml", "/rss.xml", "/index.xml"]
_TIMEOUT = 10


class _LinkParser(HTMLParser):
    """Extract <link rel="alternate" type="application/rss+xml"> from HTML."""

    def __init__(self):
        super().__init__()
        self.feeds: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        if tag != "link":
            return
        attr_dict = {k: v for k, v in attrs if v is not None}
        rel = attr_dict.get("rel", "")
        feed_type = attr_dict.get("type", "")
        href = attr_dict.get("href", "")
        if "alternate" in rel and feed_type in _FEED_TYPES and href:
            self.feeds.append({"href": href, "title": attr_dict.get("title", "")})


def _is_valid_feed(parsed) -> bool:
    return bool(parsed.entries) or parsed.feed.get("title")


def discover_feed(url: str) -> tuple[Optional[str], Optional[str]]:
    """Discover an RSS/Atom feed from any URL.

    Returns (feed_url, feed_title) or (None, None) if no feed found.
    If the URL itself is a feed, returns it directly.
    """
    # Step 1: Try URL directly as a feed
    try:
        parsed = feedparser.parse(url)
        if _is_valid_feed(parsed):
            return url, parsed.feed.get("title")
    except Exception:
        pass

    # Step 2: Fetch HTML and look for <link> tags
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "content-agent/1.0"})
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None, None

    html = resp.text
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    for link in parser.feeds:
        feed_url = urljoin(url, link["href"])
        try:
            parsed = feedparser.parse(feed_url)
            if _is_valid_feed(parsed):
                return feed_url, parsed.feed.get("title") or link.get("title")
        except Exception:
            continue

    # Step 3: Try common feed paths
    base = url.rstrip("/")
    for path in _COMMON_PATHS:
        candidate = base + path
        try:
            parsed = feedparser.parse(candidate)
            if _is_valid_feed(parsed):
                return candidate, parsed.feed.get("title")
        except Exception:
            continue

    return None, None
