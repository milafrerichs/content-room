# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 2026-03-19

### Added

- **Article browsing UI**: Full browse page with filters (feed, status, date, search), card grid with pagination, and detail view with on-demand summarization
- **On-demand summarization**: Removed automatic summarization from the pipeline; articles and podcasts are now summarized only when requested via the UI
- **One-sentence summaries**: Lightweight summaries generated automatically on discovery, providing quick previews without full summarization
- **Unified feed timeline**: Combined articles and episodes in a single chronological view grouped by day (today expanded, older collapsed), with source/search filters
- **Category view**: Tab-based feed timeline with "By Day" and "By Category" views; category filter pills for quick navigation
- **Unified feed management**: Single page to manage both podcast and article feeds, showing item counts and last-item dates per feed
- **Feed categories**: Categorize feeds by topic (e.g. "Tech", "Health"); feeds grouped by category; inline category editing via HTMX
- **Archive**: Archive feed items to hide from regular views; dedicated archive page in sidebar; archive/unarchive from feed timeline and detail pages
- **Config sync**: Feeds from config.yaml synced to database automatically during processing and via UI button
- **Run Processing button**: Trigger the full pipeline (fetch, download, transcribe) from the web dashboard
- **Settings page**: Per-task model override configuration via settings UI
- **Settings table**: Database-backed settings for LLM provider/model per task

### Changed

- Processing pipeline stops at "transcribed" for podcasts (no auto-summarization)
- Article processing removed from automatic runs (fetch only, summarize on demand)
- Feed upserts use `ON CONFLICT` instead of `INSERT OR REPLACE` to preserve user-set categories
- Unified feed query joins with feed tables to include category data
- Episode and article list views exclude archived items by default

## [0.6.0] - 2026-02-07

### Added

- **Article processing support**: RSS article feeds can now be processed alongside podcasts
- New models: `ArticleFeed`, `Article`, `ArticleSummary`
- New config options:
  - `article_feeds`: List of RSS feeds for articles
  - `article_summary_dir`: Directory for article summaries
  - `max_articles_per_day`: Limit on articles processed per run
- New database table `articles` with full CRUD operations
- New database functions: `insert_article`, `update_article_status`, `get_pending_articles`, `get_unread_articles`, `get_article_by_id`, `mark_article_read`, `get_feed_stats`, `search_articles`
- New agent methods: `fetch_article_feed()`, `process_article()`
- New MCP tools for articles:
  - `list_unread_articles`: List summarized articles not yet reviewed
  - `list_article_feeds`: List article feeds with unread/total counts
  - `get_article_summary`: Read full summary for an article
  - `get_article_content`: Read original article content from RSS
  - `mark_article_read`: Mark article as reviewed
  - `search_articles`: Search across article content
  - `resummarize_article`: Re-summarize with custom instructions
- `clean_html()` helper function to strip HTML tags from RSS content
- Articles are summarized using the `summarize_micro` pattern

### Changed

- **Package renamed**: `podcast_agent` → `content_agent`
- **Class renamed**: `PodcastAgent` → `ContentAgent`
- **MCP server renamed**: `podcast-agent` → `content-agent`
- Config field `rss_feeds` renamed to `podcast_feeds` (backwards compatible)
- Config field `summary_dir` renamed to `podcast_summary_dir` (backwards compatible)
- Database path default changed to `content_agent.db`
- Log file renamed to `content_agent.log`
- `run_processing()` now processes both podcasts and articles
- `runs` table now tracks article statistics alongside episode statistics

### Backwards Compatibility

- `rss_feeds` in config still works, mapped to `podcast_feeds`
- `summary_dir` in config still works, mapped to `podcast_summary_dir`
- Existing `episodes` table unchanged
- Existing podcast processing workflow unchanged

## [0.5.0] - 2026-02-06

### Added

- MCP server (`mcp_server.py`) with FastMCP for browsing processed podcasts
- Podcast tools: `list_unread`, `list_podcasts`, `get_summary`, `get_transcript`, `mark_read`, `resummarize`, `search_episodes`
- Fabric pattern tools: `get_sponsors`, `get_micro_summary`, `get_insights`, `get_recommendations`
- Additional summary models: `MicroSummary`, `Insights`, `Recommendations`, `SponsorInfo`
- `summarizer.py` with cached agent pattern for multiple Fabric patterns

## [0.4.0] - 2026-02-05

### Added

- pydantic-ai summarization using Claude Haiku 4.5, replacing broken Fabric CLI
- SQLite state tracking (`db.py`) with `episodes` and `runs` tables
- `PodcastSummary` structured output model with markdown formatting
- `run.py` worker entry point for launchd scheduling
- launchd plist for 4-hour scheduled runs
- `db_path` and `whisper_model` config fields
- Path expansion (`~` → home directory) via model validator on `AgentConfig`

### Removed

- `fabric_pattern` and `mcp_endpoint` config fields
- `schedule` dependency and `schedule_daily_run()` method
- Duplicate Huberman Lab feeds in `config.yaml`

### Fixed

- `~/` paths created literal `~/` directories instead of expanding to home directory
- Scheduler sleep interval was 13 hours, making it effectively unusable
