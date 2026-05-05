# Per-Task Model Configuration

## Context

Currently all 7 summarization tasks use the same global LLM config (`llm_provider` + `active_model`). Some tasks (like `one_sentence`) are lightweight and could use a cheaper/faster model, while others (like `extract_wisdom`) benefit from a more capable model. This change adds per-task model overrides configurable via `config.yaml` and a new Settings page in the web UI.

## Design

- **YAML**: Add optional `task_models` dict to `AgentConfig` (backward compatible — empty by default)
- **SQLite**: New `settings` table stores UI-driven overrides (avoids writing back to YAML)
- **Resolution order**: SQLite override > YAML per-task override > global default
- **No summarizer changes needed** — functions already accept `provider`, `model`, `ollama_base_url` as params

## Task Names (7 tasks)

| Task Key | Description | Used In |
|---|---|---|
| `extract_wisdom` | Full podcast summary | agent.py:322 |
| `summarize_micro` | Quick 3-point summary | agent.py:584, mcp_server.py:577 |
| `extract_sponsors` | Sponsor extraction | agent.py:309, mcp_server.py:546 |
| `extract_insights` | 10 key insights | mcp_server.py:606 |
| `extract_recommendations` | Actionable recs | mcp_server.py:637 |
| `one_sentence` | Single sentence summary | agent.py:268 |
| `custom_instructions` | Re-summarization | mcp_server.py:223, 510 |

## Implementation Steps

### Step 1: Add `TaskModelOverride` model and config method (`models.py`)

- New `TaskModelOverride(BaseModel)` with optional `provider`, `model`, `ollama_base_url`
- Add `task_models: dict[str, TaskModelOverride] = {}` to `AgentConfig`
- Add `TASK_NAMES` constant list
- Add `get_task_model_kwargs(task_name: str) -> dict` method that returns `{"provider": ..., "model": ..., "ollama_base_url": ...}` with fallback to global defaults

### Step 2: Update call sites in `agent.py` (4 sites)

Replace:
```python
provider=self.config.llm_provider,
model=self.config.active_model,
ollama_base_url=self.config.ollama_base_url,
```
With:
```python
**self.config.get_task_model_kwargs("task_name")
```

- Line 268: `one_sentence`
- Line 309: `extract_sponsors`
- Line 322: `extract_wisdom`
- Line 584: `summarize_micro`

### Step 3: Update call sites in `mcp_server.py` (6 sites)

Same pattern replacement:
- Line 223: `custom_instructions`
- Line 510: `custom_instructions`
- Line 546: `extract_sponsors`
- Line 577: `summarize_micro`
- Line 606: `extract_insights`
- Line 637: `extract_recommendations`

### Step 4: Add `settings` table to `db.py`

- `CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)`
- `get_task_model_overrides(conn) -> dict[str, TaskModelOverride]`
- `set_task_model_override(conn, task_name, override: TaskModelOverride)`
- `delete_task_model_override(conn, task_name)`

### Step 5: Add config merge helper

- `get_effective_config(config, conn)` — merges SQLite overrides on top of YAML config
- Used by web routes and processing.py when building config for background tasks

### Step 6: Create Settings route (`src/content_agent/web/routes/settings.py`)

- `GET /settings` — renders settings page with global defaults + per-task table
- `POST /settings/task-model/{task_name}` — saves override to SQLite, returns HTMX partial
- `DELETE /settings/task-model/{task_name}` — removes override (reverts to default)

### Step 7: Create Settings templates

- `templates/settings/settings.html` — main page with global config display + task model table
- `templates/settings/_task_model_row.html` — HTMX partial for inline editing

Table layout:
```
Task                 | Provider (dropdown) | Model (text input) | [Save] [Reset]
extract_wisdom       | anthropic           | claude-sonnet-4... | [Save] [Reset]
summarize_micro      | (default)           | (default)          | [Edit]
...
```

### Step 8: Add Settings nav link (`base.html`)

- Gear icon + "Settings" link in sidebar, after Run History

### Step 9: Register router (`app.py`)

- Import and include `settings.router`

## Files to Modify

| File | Type |
|---|---|
| `src/content_agent/models.py` | Edit |
| `src/content_agent/agent.py` | Edit |
| `src/content_agent/mcp_server.py` | Edit |
| `src/content_agent/db.py` | Edit |
| `src/content_agent/web/app.py` | Edit |
| `src/content_agent/templates/base.html` | Edit |
| `src/content_agent/web/routes/settings.py` | New |
| `src/content_agent/templates/settings/settings.html` | New |
| `src/content_agent/templates/settings/_task_model_row.html` | New |

## Verification

1. Start the web app, navigate to `/settings` — should show all 7 tasks with global defaults
2. Set an override for `one_sentence` to use ollama/llama3.2 — verify it saves and displays
3. Run article processing — verify `one_sentence` uses ollama while other tasks use global default
4. Delete the override — verify it reverts to global default
5. Add `task_models` section to config.yaml — verify it loads correctly
6. Verify existing config.yaml without `task_models` still works (backward compat)
