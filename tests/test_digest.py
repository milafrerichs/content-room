"""Tests for daily digest generation and Slack delivery."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from content_agent.queries import digest as digest_queries
from content_agent.digest import DigestGenerator
from content_agent.delivery import SlackDelivery, resolve_webhook_url
from content_agent.models import DailyDigestOutput, DigestConfig, DigestItem


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_digest_item(
    title="Test Title",
    feed_name="Test Feed",
    published_date="2025-01-01",
    one_sentence_summary="A brief summary of the test article content.",
    item_type="article",
) -> DigestItem:
    return DigestItem(
        title=title,
        feed_name=feed_name,
        published_date=published_date,
        one_sentence_summary=one_sentence_summary,
        item_type=item_type,
    )


def make_digest_output(
    target_date="2025-01-01",
    overall_summary="A productive day with AI and productivity insights.",
    top_items=None,
    items=None,
) -> DailyDigestOutput:
    return DailyDigestOutput(
        date=target_date,
        overall_summary=overall_summary,
        top_items=top_items or ["AI advances in 2025.", "New productivity tools released."],
        items=items or [make_digest_item()],
    )


def _insert_article(conn, *, title, feed_name, published_date, one_sentence_summary=None, status="summarized"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO articles (feed_name, title, url, published_date, content, status, one_sentence_summary)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (feed_name, title, f"https://example.com/{title}", published_date, "content", status, one_sentence_summary),
    )
    conn.commit()
    cur.close()


def _insert_episode(conn, *, title, podcast_name, published_date, one_sentence_summary=None, status="summarized"):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO episodes (podcast_name, title, audio_url, published_date, status, one_sentence_summary)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (podcast_name, title, f"https://example.com/{title}.mp3", published_date, status, one_sentence_summary),
    )
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# DB: get_items_for_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("item_type,expected_count", [
    ("article", 2),
    ("episode", 2),
    ("mixed", 2),
])
def test_get_items_for_date(pg_conn, item_type, expected_count):
    target = "2025-01-15"
    other = "2025-01-14"

    if item_type == "article":
        _insert_article(pg_conn, title="Article A", feed_name="Feed1", published_date=target, one_sentence_summary="Summary A")
        _insert_article(pg_conn, title="Article B", feed_name="Feed1", published_date=target, one_sentence_summary="Summary B")
        _insert_article(pg_conn, title="Article Old", feed_name="Feed1", published_date=other, one_sentence_summary="Old")
    elif item_type == "episode":
        _insert_episode(pg_conn, title="Ep A", podcast_name="Pod1", published_date=target, one_sentence_summary="Ep Summary A")
        _insert_episode(pg_conn, title="Ep B", podcast_name="Pod1", published_date=target, one_sentence_summary="Ep Summary B")
        _insert_episode(pg_conn, title="Ep Old", podcast_name="Pod1", published_date=other, one_sentence_summary="Old ep")
    elif item_type == "mixed":
        _insert_article(pg_conn, title="Article A", feed_name="Feed1", published_date=target, one_sentence_summary="Summary A")
        _insert_article(pg_conn, title="Article Old", feed_name="Feed1", published_date=other, one_sentence_summary="Old")
        _insert_episode(pg_conn, title="Ep A", podcast_name="Pod1", published_date=target, one_sentence_summary="Ep Summary A")
        _insert_episode(pg_conn, title="Ep Old", podcast_name="Pod1", published_date=other, one_sentence_summary="Old ep")

    rows = digest_queries.get_items_for_date(pg_conn, date(2025, 1, 15))
    assert len(rows) == expected_count
    titles = [r["title"] for r in rows]
    assert "Article Old" not in titles
    assert "Ep Old" not in titles


def test_get_items_for_date_excludes_unsummarized(pg_conn):
    _insert_article(pg_conn, title="Ready", feed_name="F", published_date="2025-01-15", one_sentence_summary="s", status="summarized")
    _insert_article(pg_conn, title="Pending", feed_name="F", published_date="2025-01-15", status="discovered")

    rows = digest_queries.get_items_for_date(pg_conn, date(2025, 1, 15))
    assert len(rows) == 1
    assert rows[0]["title"] == "Ready"


def test_get_items_for_date_returns_empty_for_no_items(pg_conn):
    rows = digest_queries.get_items_for_date(pg_conn, date(2025, 1, 15))
    assert rows == []


# ---------------------------------------------------------------------------
# DigestGenerator.build
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_reuses_stored_summaries(pg_conn, tmp_config):
    _insert_article(
        pg_conn,
        title="Article with summary",
        feed_name="Feed",
        published_date="2025-01-15",
        one_sentence_summary="Already summarized content.",
    )

    with patch("content_agent.digest.generate_digest_meta") as mock_meta, \
         patch("content_agent.digest.summarize_one_sentence") as mock_one_sentence:
        mock_meta.return_value = MagicMock(
            overall_summary="Overall summary.",
            top_item_titles=["Article with summary"],
        )

        generator = DigestGenerator()
        result = await generator.build(pg_conn, tmp_config, target_date=date(2025, 1, 15))

    mock_one_sentence.assert_not_called()
    assert result.date == "2025-01-15"
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_build_generates_missing_summaries(pg_conn, tmp_config):
    _insert_article(
        pg_conn,
        title="Article no summary",
        feed_name="Feed",
        published_date="2025-01-15",
        one_sentence_summary=None,
    )

    with patch("content_agent.digest.generate_digest_meta") as mock_meta, \
         patch("content_agent.digest.summarize_one_sentence") as mock_one_sentence:
        mock_meta.return_value = MagicMock(
            overall_summary="Generated overall summary.",
            top_item_titles=["Article no summary"],
        )
        mock_one_sentence.return_value = "Generated one-sentence summary."

        generator = DigestGenerator()
        result = await generator.build(pg_conn, tmp_config, target_date=date(2025, 1, 15))

    mock_one_sentence.assert_called_once()
    assert result.items[0].one_sentence_summary == "Generated one-sentence summary."


@pytest.mark.asyncio
async def test_build_returns_empty_digest_when_no_items(pg_conn, tmp_config):
    with patch("content_agent.digest.generate_digest_meta") as mock_meta:
        mock_meta.return_value = MagicMock(
            overall_summary="No items today.",
            top_item_titles=[],
        )

        generator = DigestGenerator()
        result = await generator.build(pg_conn, tmp_config, target_date=date(2025, 1, 15))

    assert result.items == []


# ---------------------------------------------------------------------------
# DigestGenerator.format_slack_blocks
# ---------------------------------------------------------------------------

def test_format_slack_blocks_has_required_structure():
    digest = make_digest_output(
        target_date="2025-01-15",
        overall_summary="A day of insights.",
        top_items=["AI is transforming software.", "New Python tools released."],
        items=[
            make_digest_item(title="AI Article", feed_name="Tech Feed", one_sentence_summary="AI is growing fast."),
            make_digest_item(title="Python News", feed_name="Dev Feed", one_sentence_summary="Python 4 announced.", item_type="episode"),
        ],
    )

    generator = DigestGenerator()
    payload = generator.format_slack_blocks(digest)

    assert "blocks" in payload
    blocks = payload["blocks"]
    block_types = [b["type"] for b in blocks]
    assert "header" in block_types
    assert "section" in block_types
    assert "divider" in block_types


def test_format_slack_blocks_contains_date():
    digest = make_digest_output(target_date="2025-01-15")
    generator = DigestGenerator()
    payload = generator.format_slack_blocks(digest)

    assert "2025-01-15" in str(payload)


def test_format_slack_blocks_contains_overall_summary():
    digest = make_digest_output(overall_summary="Unique sentinel summary text.")
    generator = DigestGenerator()
    payload = generator.format_slack_blocks(digest)

    assert "Unique sentinel summary text." in str(payload)


def test_format_slack_blocks_contains_top_items():
    digest = make_digest_output(top_items=["Sentinel top item one.", "Sentinel top item two."])
    generator = DigestGenerator()
    payload = generator.format_slack_blocks(digest)

    payload_str = str(payload)
    assert "Sentinel top item one." in payload_str
    assert "Sentinel top item two." in payload_str


def test_format_slack_blocks_contains_each_item_title():
    items = [
        make_digest_item(title="Unique Article Title Alpha"),
        make_digest_item(title="Unique Article Title Beta"),
    ]
    digest = make_digest_output(items=items)
    generator = DigestGenerator()
    payload = generator.format_slack_blocks(digest)

    payload_str = str(payload)
    assert "Unique Article Title Alpha" in payload_str
    assert "Unique Article Title Beta" in payload_str


# ---------------------------------------------------------------------------
# SlackDelivery (boundary tests)
# ---------------------------------------------------------------------------

def test_slack_delivery_posts_to_webhook():
    payload = {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "Test"}}]}

    with patch("content_agent.delivery.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        delivery = SlackDelivery("https://hooks.slack.com/services/test/webhook")
        result = delivery.send(payload)

    assert result is True
    mock_post.assert_called_once_with(
        "https://hooks.slack.com/services/test/webhook",
        json=payload,
        timeout=10,
    )


def test_slack_delivery_returns_false_on_non_200():
    with patch("content_agent.delivery.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        delivery = SlackDelivery("https://hooks.slack.com/services/test/webhook")
        result = delivery.send({"blocks": []})

    assert result is False


def test_slack_delivery_returns_false_on_exception():
    with patch("content_agent.delivery.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection error")
        delivery = SlackDelivery("https://hooks.slack.com/services/test/webhook")
        result = delivery.send({"blocks": []})

    assert result is False


# ---------------------------------------------------------------------------
# resolve_webhook_url
# ---------------------------------------------------------------------------

def test_resolve_webhook_url_uses_config_value():
    config = DigestConfig(slack_webhook_url="https://hooks.slack.com/config-url")
    assert resolve_webhook_url(config) == "https://hooks.slack.com/config-url"


def test_resolve_webhook_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/env-url")
    config = DigestConfig(slack_webhook_url="")
    assert resolve_webhook_url(config) == "https://hooks.slack.com/env-url"


def test_resolve_webhook_url_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    config = DigestConfig(slack_webhook_url="")
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL"):
        resolve_webhook_url(config)
