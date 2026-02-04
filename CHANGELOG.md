# Changelog

## 0.4.0

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
