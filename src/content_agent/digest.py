"""Daily digest generation and Slack formatting."""

import logging
from datetime import date, timedelta

from .models import AgentConfig, DailyDigestOutput, DigestItem
from .queries import digest as digest_queries
from .summarizer import generate_digest_meta, summarize_one_sentence

logger = logging.getLogger(__name__)


class DigestGenerator:
    async def build(
        self,
        conn,
        config: AgentConfig,
        target_date: date | None = None,
    ) -> DailyDigestOutput:
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        rows = digest_queries.get_items_for_date(conn, target_date)

        kwargs = config.get_task_model_kwargs("digest_meta")
        items = []
        for row in rows:
            summary = row["one_sentence_summary"]
            if not summary:
                try:
                    summary = await summarize_one_sentence(
                        row["title"],
                        provider=kwargs["provider"],
                        model=kwargs["model"],
                        ollama_base_url=kwargs["ollama_base_url"],
                    )
                except Exception as e:
                    logger.warning("Could not generate summary for %r: %s", row["title"], e)
                    summary = row["title"]
            items.append(
                DigestItem(
                    title=row["title"],
                    feed_name=row["feed_name"],
                    published_date=str(row["published_date"]),
                    one_sentence_summary=summary,
                    item_type=row["item_type"],
                )
            )

        meta = await generate_digest_meta(
            items,
            provider=kwargs["provider"],
            model=kwargs["model"],
            ollama_base_url=kwargs["ollama_base_url"],
        )

        top_items = self._resolve_top_items(items, meta.top_item_titles)

        return DailyDigestOutput(
            date=target_date.isoformat(),
            overall_summary=meta.overall_summary,
            top_items=top_items,
            items=items,
        )

    def _resolve_top_items(self, items: list[DigestItem], titles: list[str]) -> list[str]:
        by_title = {item.title: item for item in items}
        result = []
        for title in titles:
            item = by_title.get(title)
            if item:
                result.append(f"*{item.title}* ({item.feed_name}) — {item.one_sentence_summary}")
            else:
                result.append(title)
        return result

    def format_slack_blocks(self, digest: DailyDigestOutput) -> dict:
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Daily Digest — {digest.date}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_{digest.overall_summary}_"},
            },
            {"type": "divider"},
        ]

        if digest.top_items:
            top_text = "*Top Stories*\n" + "\n".join(f"• {item}" for item in digest.top_items)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": top_text}})
            blocks.append({"type": "divider"})

        if digest.items:
            all_items_text = "*All Items*\n" + "\n".join(
                f"• *{item.title}* ({item.feed_name}) — {item.one_sentence_summary}"
                for item in digest.items
            )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": all_items_text}})

        return {"blocks": blocks}

    def format_markdown(self, digest: DailyDigestOutput) -> str:
        lines = [
            f"# Daily Digest — {digest.date}",
            "",
            f"_{digest.overall_summary}_",
            "",
        ]
        if digest.top_items:
            lines += ["## Top Stories", ""]
            for item in digest.top_items:
                lines.append(f"- {item}")
            lines.append("")
        if digest.items:
            lines += ["## All Items", ""]
            for item in digest.items:
                lines.append(f"- **{item.title}** ({item.feed_name}) — {item.one_sentence_summary}")
        return "\n".join(lines)
