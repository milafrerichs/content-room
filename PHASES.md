# Org & Team Sharing — Implementation Phases

Branch: `worktree-feat+org-sharing`

## What's done (Phase 1 ✅)

- Clerk JWT verification (`src/content_agent/web/auth.py` — `ClerkJWTVerifier`, `UserContext`)
- `AuthMiddleware` in `app.py` — redirects to `/login`, 401 for HTMX
- Login / logout pages (`templates/auth/login.html`, `logout.html`) using Clerk JS SDK
- Alembic migration `002_auth` — `users` table, `owner_type`/`owner_id` on feed tables, composite unique index
- `queries/users.py` — `upsert_user`, `get_user`
- `queries/feeds.py` — all functions scoped by `(owner_type, owner_id)`; `owner_type`/`owner_id` are **required** params (no defaults)
- All route handlers require `CurrentUser` dependency
- `scripts/migrate_to_user.py` — one-shot script to claim existing feeds for a Clerk user ID
- Startup no longer syncs config.yaml feeds (feeds are managed via UI per-user)

### Env vars needed
```
CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_SECRET_KEY=sk_live_...
CLERK_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
CLERK_WEBHOOK_SECRET=whsec_...   # needed from Phase 2
```

---

## Architecture rules to follow in all phases

- **PostgreSQL** — psycopg2, `%s` placeholders, `RealDictCursor`
- **Alembic** for every schema change — one file per phase, numbered `003_orgs`, `004_teams`, `005_sharing`, `006_user_item_state`
- **Raw+DC pattern** — new query functions go in `src/content_agent/queries/`; use `_fetchall`, `_fetchone`, `_execute` from `db.py`; return `list[dict]` or `dict | None`
- **No ORM** — raw SQL only
- Feed ownership model: `owner_type` (`'user'`|`'team'`|`'org'`) + `owner_id` (Clerk ID string) on `podcast_feeds` / `article_feeds`

---

## Phase 2 — Org Feeds

### Goal
Org admins can create org-scoped feeds. All org members automatically see those feeds in their timeline.

### DB — `alembic/versions/003_orgs.py`
```sql
CREATE TABLE organizations (
    clerk_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT,
    image_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE org_members (
    org_id TEXT NOT NULL REFERENCES organizations(clerk_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'org:member',   -- 'org:admin' | 'org:member'
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX idx_org_members_user ON org_members (user_id);
```

### New files
- `src/content_agent/queries/orgs.py`
  - `upsert_org(conn, clerk_id, name, slug, image_url)`
  - `delete_org(conn, clerk_id)`
  - `upsert_org_member(conn, org_id, user_id, role)`
  - `remove_org_member(conn, org_id, user_id)`
  - `get_user_orgs(conn, user_id) -> list[dict]` — returns org rows + role
- `src/content_agent/web/routes/webhooks.py` — `POST /webhooks/clerk`
  - Verify svix signature using `CLERK_WEBHOOK_SECRET` (`svix` package already installed)
  - Handle: `organization.created`, `organization.deleted`, `organizationMembership.created`, `organizationMembership.deleted`

### Modified files
- `src/content_agent/web/deps.py`
  - `UserContext` gains `all_org_ids: list[str]`, `org_role: str | None` (populated from `org_members` table)
  - `active_org_id` already comes from JWT `org_id` claim — verify it's in `UserContext`
- `src/content_agent/queries/feeds.py`
  - `get_unified(conn, user_id, active_org_id, ...)` — UNION user feeds + org feeds:
    ```sql
    WHERE (pf.owner_type='user' AND pf.owner_id=<user_id>)
       OR (pf.owner_type='org' AND pf.owner_id=<active_org_id>)
    ```
  - `get_podcasts_with_stats`, `get_articles_with_stats`, `get_all_sources`, `get_all_categories` — same UNION pattern
- `src/content_agent/web/app.py` — register `webhooks.router`
- `src/content_agent/web/routes/feed.py`
  - Pass `active_org_id` to all feed queries
  - Feed creation: `owner_type` from a hidden form field (default `'user'`; `'org'` if org context active)
  - Org feed creation guard: `if user.org_role != 'org:admin': raise HTTPException(403)`
  - New route: `POST /context/switch-org` — sets `active_org_id` cookie, redirects to `/feed`

### Templates
- `base.html` — org switcher dropdown in sidebar: "Personal" ↔ org name(s)
  - Reads `user.all_org_ids` and org names from context
  - POST to `/context/switch-org` on select
- `feed/feeds.html` — separate "Org Feeds" section; "Add to Org" button for `org:admin` only
- `feed/timeline.html` — optional source badge: "Personal" vs "[Org Name]"

### Checklist
- [ ] Migration `003_orgs.py` written and `alembic upgrade head` runs clean
- [ ] `queries/orgs.py` — all 5 functions implemented
- [ ] `webhooks.py` — svix signature verification + 4 event handlers
- [ ] Webhook route registered in `app.py`
- [ ] `UserContext` updated with `all_org_ids`, org members loaded in `get_current_user`
- [ ] `feeds.py` `get_unified` extended to union user + org feeds
- [ ] `feed.py` passes `active_org_id` to all feed queries
- [ ] `/context/switch-org` route implemented
- [ ] Org switcher in `base.html`
- [ ] "Org Feeds" section in `feeds.html`
- [ ] Source badge in `timeline.html`
- [ ] **Verify**: Create org in Clerk dashboard → webhook fires → `organizations` + `org_members` tables populated
- [ ] **Verify**: Org switcher appears in sidebar; switching shows org feeds
- [ ] **Verify**: Second user in org sees org-owned feeds

---

## Phase 3 — Team Feeds

### Goal
Teams within an org can have their own feeds (Clerk calls these "organization groups" in the API).

### DB — `alembic/versions/004_teams.py`
```sql
CREATE TABLE teams (
    clerk_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(clerk_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_teams_org ON teams (org_id);

CREATE TABLE team_members (
    team_id TEXT NOT NULL REFERENCES teams(clerk_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX idx_team_members_user ON team_members (user_id);
```

### New files
- `src/content_agent/queries/teams.py`
  - `upsert_team(conn, clerk_id, org_id, name)`
  - `delete_team(conn, clerk_id)`
  - `upsert_team_member(conn, team_id, user_id, role)`
  - `remove_team_member(conn, team_id, user_id)`
  - `get_user_teams(conn, user_id) -> list[dict]`

### Modified files
- `webhooks.py` — add handlers: `organizationGroup.created/deleted`, `organizationGroupMembership.created/deleted`
- `deps.py` — `UserContext` gains `team_ids: list[str]`, `active_team_id: str | None` (from `active_team_id` cookie)
- `queries/feeds.py` — `get_unified` extended to union user + org + team feeds:
  ```sql
  WHERE (owner_type='user' AND owner_id=<user_id>)
     OR (owner_type='org' AND owner_id=<active_org_id>)
     OR (owner_type='team' AND owner_id = ANY(<team_ids>))
  ```
- `feed.py` — pass `team_ids` to feed queries; new route `POST /context/switch-team`
- `base.html` — team switcher nested under org; sets `active_team_id` cookie
- `feed/feeds.html` — "Team Feeds" section
- `feed/timeline.html` — source badge extended: "Personal" / "Team: [Name]" / "Org: [Name]"

### Checklist
- [ ] Migration `004_teams.py` written and runs clean
- [ ] `queries/teams.py` — all 5 functions
- [ ] `webhooks.py` — 4 new event handlers for team events
- [ ] `UserContext` updated with `team_ids`, loaded in `get_current_user`
- [ ] `feeds.py` `get_unified` extended to include team feeds
- [ ] `/context/switch-team` route
- [ ] Team switcher in `base.html`
- [ ] "Team Feeds" section in `feeds.html`
- [ ] Source badges in `timeline.html`
- [ ] **Verify**: Create team in Clerk → webhook → `teams` + `team_members` populated
- [ ] **Verify**: Team member sees team feeds; non-member does not

---

## Phase 4 — Feed Sharing & Discovery

### Goal
Org admins mark feeds as "shared" (discoverable). Other org members can subscribe to them. Content is processed once per unique URL regardless of how many subscribers there are.

### DB — `alembic/versions/005_sharing.py`
```sql
-- Canonical feed: one row per unique RSS URL, content processed once
CREATE TABLE canonical_feeds (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    feed_type TEXT NOT NULL,   -- 'podcast' | 'article'
    last_fetched_at TIMESTAMPTZ
);

ALTER TABLE podcast_feeds ADD COLUMN canonical_feed_id INTEGER REFERENCES canonical_feeds(id);
ALTER TABLE article_feeds  ADD COLUMN canonical_feed_id INTEGER REFERENCES canonical_feeds(id);
ALTER TABLE episodes ADD COLUMN canonical_feed_id INTEGER REFERENCES canonical_feeds(id);
ALTER TABLE articles  ADD COLUMN canonical_feed_id INTEGER REFERENCES canonical_feeds(id);

ALTER TABLE podcast_feeds ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE article_feeds  ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE feed_subscriptions (
    id SERIAL PRIMARY KEY,
    subscriber_type TEXT NOT NULL,   -- 'user' | 'team'
    subscriber_id TEXT NOT NULL,
    feed_type TEXT NOT NULL,         -- 'podcast' | 'article'
    feed_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (subscriber_type, subscriber_id, feed_type, feed_id)
);
CREATE INDEX idx_feed_subs_subscriber ON feed_subscriptions (subscriber_type, subscriber_id);
```

### New files
- `src/content_agent/queries/subscriptions.py`
  - `get_discoverable_feeds(conn, org_id) -> list[dict]` — `WHERE owner_type='org' AND owner_id=%s AND is_shared=TRUE`
  - `subscribe(conn, subscriber_type, subscriber_id, feed_type, feed_id)`
  - `unsubscribe(conn, subscriber_type, subscriber_id, feed_type, feed_id)`
  - `get_subscriptions(conn, subscriber_type, subscriber_id) -> list[dict]`
- `src/content_agent/templates/feed/discover.html` — org feed discovery page

### Modified files
- `src/content_agent/agent.py`
  - `_get_or_create_canonical_feed(conn, url, feed_type)` — `INSERT INTO canonical_feeds ... ON CONFLICT(url) DO NOTHING` then `SELECT`
  - Processing pipeline sets `canonical_feed_id` on new episodes/articles
  - Dedup: process each unique URL once (key on `canonical_feeds.url`)
- `queries/feeds.py`
  - `get_unified` extended to include content from subscribed feeds (JOIN `feed_subscriptions`)
  - `toggle_shared(conn, feed_type, feed_id, owner_type, owner_id, is_shared: bool)`
- `feed.py` (new routes)
  - `GET /feeds/discover` — org-shared feeds not yet subscribed by current user
  - `POST /feeds/{feed_type}/{feed_id}/subscribe` — HTMX swap
  - `DELETE /feeds/{feed_type}/{feed_id}/unsubscribe` — HTMX swap
  - `POST /feeds/{feed_type}/{feed_id}/share` — toggle `is_shared` (org admin only)
- `feed/feeds.html` — share toggle on feed cards (admin); "Subscribed" badge

### Checklist
- [ ] Migration `005_sharing.py` runs clean
- [ ] `queries/subscriptions.py` — all 4 functions
- [ ] `agent.py` — `_get_or_create_canonical_feed` and dedup logic
- [ ] `queries/feeds.py` — `get_unified` includes subscribed feeds; `toggle_shared`
- [ ] New routes in `feed.py` — discover, subscribe, unsubscribe, share toggle
- [ ] `discover.html` template
- [ ] Share toggle in `feeds.html`
- [ ] **Verify**: `canonical_feeds` has one row per unique URL after processing
- [ ] **Verify**: Admin shares feed → second user visits `/feeds/discover` → subscribes → content appears in timeline
- [ ] **Verify**: `feed_subscriptions` table has expected rows

---

## Phase 5 — Per-User Read State

### Goal
Replace the global `read_at`/`archived_at`/`read_later_at` columns on `episodes`/`articles` with per-user interaction records so two users sharing an org feed have independent read state.

### DB — `alembic/versions/006_user_item_state.py`
```sql
CREATE TABLE user_item_state (
    user_id TEXT NOT NULL REFERENCES users(clerk_id) ON DELETE CASCADE,
    item_kind TEXT NOT NULL,   -- 'episode' | 'article'
    item_id INTEGER NOT NULL,
    read_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    read_later_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, item_kind, item_id)
);
CREATE INDEX idx_user_item_state ON user_item_state (user_id, item_kind);
```

**Keep** the existing `read_at`/`archived_at`/`read_later_at` columns on `episodes`/`articles` for one release — stop writing to them, read from `user_item_state` instead. Drop columns in a follow-up migration once validated.

### New files
- `src/content_agent/queries/item_state.py`
  - `upsert_state(conn, user_id, item_kind, item_id, **fields)` — `INSERT ... ON CONFLICT DO UPDATE SET`
  - `get_state(conn, user_id, item_kind, item_id) -> dict | None`

### Modified files
- `queries/feeds.py` — `get_unified` LEFT JOINs `user_item_state` on `(user_id=%s AND item_kind=... AND item_id=...)` to attach per-user read state to each row
- All mark-read / archive / read-later routes — call `upsert_state(conn, user.user_id, ...)` instead of writing to `episodes`/`articles` columns
- `queries/episodes.py` + `queries/articles.py` — update `mark_read`, `archive`, `unarchive`, `mark_read_later`, `unmark_read_later` to use `user_item_state`

### Checklist
- [ ] Migration `006_user_item_state.py` runs clean
- [ ] `queries/item_state.py` — `upsert_state` and `get_state`
- [ ] `get_unified` in `feeds.py` LEFT JOINs `user_item_state`
- [ ] All 5 state-mutation routes updated to use `upsert_state`
- [ ] `episodes.py` + `articles.py` mark-read/archive functions updated
- [ ] **Verify**: Two users see same org feed item; User A marks read → `user_item_state` has row for A only
- [ ] **Verify**: User B's view shows item still unread
- [ ] Follow-up: drop old `read_at`/`archived_at`/`read_later_at` columns from `episodes`/`articles` (separate commit)

---

## Session startup checklist (for each phase)

Before starting a new session, read:
1. This file (`PHASES.md`)
2. `src/content_agent/queries/feeds.py` — understand the current `get_unified` signature
3. `src/content_agent/web/deps.py` — understand `UserContext` fields
4. `src/content_agent/web/app.py` — understand registered routers

Key constraint: **`owner_type` and `owner_id` are required params** in all feed query functions — no defaults. Always pass them explicitly.
