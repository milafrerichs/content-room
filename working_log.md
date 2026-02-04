# Working Log

## 2026-02-04 — v0.4.0: pydantic-ai + launchd Implementation

### Bug Fixes
- **Duplicate feeds** — Removed 2 duplicate Huberman entries from `config.yaml`
- **`~` not expanded** — Added `@model_validator` to `AgentConfig` that calls `.expanduser()` on all Path fields
- **Fabric CLI broken** — Replaced entirely with pydantic-ai summarizer
- **Scheduler sleeps 13h** — Removed `schedule_daily_run()` and `schedule` dependency; replaced with launchd

### New Files
| File | Purpose |
|------|---------|
| `src/podcast_agent/db.py` | SQLite state tracking (episodes + runs tables) |
| `src/podcast_agent/summarizer.py` | pydantic-ai agent with lazy init (Claude Haiku 4.5) |
| `run.py` | Worker entry point for launchd |
| `de.milafrerichs.podcast-agent.plist` | launchd job (every 4 hours) |
| `.env.example` | Template for API key |

### Modified Files
| File | Key Changes |
|------|-------------|
| `models.py` | Added `PodcastSummary` model with `to_markdown()`, added `db_path`/`whisper_model` to `AgentConfig`, removed `fabric_pattern`/`mcp_endpoint`, added path expansion validator |
| `agent.py` | Replaced `summarize_with_fabric` with `summarize_episode` using pydantic-ai, integrated DB state tracking in `process_episode`, renamed main method to `run_processing`, removed `schedule` import and `schedule_daily_run` |
| `__init__.py` | Updated exports, bumped version to 0.4.0 |
| `config.yaml` | Removed duplicates, removed fabric fields, added `db_path`/`whisper_model` |
| `pyproject.toml` | Added `pydantic-ai`, removed `schedule` |
| `.gitignore` | Added `*.db`, `.env`, `podcast_agent.log`, `~/` |

### To activate the launchd job
```bash
# 1. Create .env with your API key
echo "ANTHROPIC_API_KEY=sk-..." > .env

# 2. Test manually first
uv run python run.py

# 3. Install the launchd job
cp de.milafrerichs.podcast-agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.milafrerichs.podcast-agent.plist

# 4. Verify
launchctl list | grep podcast
```
