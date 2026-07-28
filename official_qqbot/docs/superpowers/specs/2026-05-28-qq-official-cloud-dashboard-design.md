# QQ Official WebSocket + Cloud Dashboard Design

Date: 2026-05-28

## Goal

Migrate the bot away from Koishi/webhook bridge mode and make the official QQ bot path the primary runtime:

- Receive QQ events through the official WebSocket gateway.
- Send replies through QQ official HTTP OpenAPI.
- Keep existing user-facing bot commands where practical.
- Move user identity, email binding, bans, permissions, limits, usage, and logs into a cloud database.
- Serve an admin dashboard at `https://bot.miracle.vin`.

The first production milestone is a stable bot that no longer depends on Koishi for QQ ingress. The second milestone is centralized cloud state. The third milestone is a dashboard that controls that state.

## Current State

The repository currently has:

- `bot.py` as the main Python worker.
- A hand-written official WebSocket implementation in `bot.py`.
- Koishi and NoneBot bridge paths that forward events into Python.
- QQ OpenAPI message send logic in `send_group_msg`, `send_c2c_msg`, and `reply_plain`.
- Local JSON state under `data/`:
  - `email_binds.json`
  - `admins.json`
  - `staff.json`
  - `banned.json`
  - `cooldowns.json`
  - `sign_official.json`
  - `ads.json`
- Persistent per-user resource limits in `shared_cooldown.py`.
- Global limit identity propagation via `limit_user_id`.

The old Koishi bridge has been useful for compatibility, but it adds an extra process, a plugin layer, a webhook fallback, and a second event identity model. The new design removes it from the primary path.

## Recommended Architecture

Use three services:

1. Bot worker
   - Python service.
   - Connects to QQ official WebSocket.
   - Normalizes events into the existing internal context shape.
   - Executes bot commands.
   - Sends replies through QQ HTTP OpenAPI.
   - Reads and writes cloud state through the control API.

2. Control API
   - Python FastAPI service.
   - Owns database access.
   - Provides authenticated APIs for bot state and dashboard state.
   - Writes audit logs for admin changes and resource operations.

3. Dashboard
   - Web frontend at `https://bot.miracle.vin`.
   - Reads from and writes to the Control API.
   - Shows users, bindings, bans, permissions, limits, usage, inventory, and logs.

PostgreSQL is the system of record. Redis is optional later for short TTL counters or live log streaming, but the first version should work without Redis.

## QQ Runtime

### Event Ingress

The bot worker receives QQ events through the official WebSocket gateway.

Implementation preference:

- Use `botpy` if it can expose all required event fields reliably:
  - `GROUP_AT_MESSAGE_CREATE`
  - full group message events where available
  - `C2C_MESSAGE_CREATE`
  - global user identity when provided by QQ
  - message id for reply deduplication and `msg_id`
- Keep a small adapter layer so the rest of the bot consumes a stable internal event object.
- If `botpy` hides fields needed for global identity or full-message handling, keep the existing manual WebSocket client but move it out of `bot.py` into a dedicated gateway module.

The event adapter must output:

- `type`: `group` or `c2c`
- `group_openid`
- `user_openid`
- `limit_user_id`
- `msg_id`
- `content`
- `raw_content`
- `event_type`
- `is_at`
- `is_full_message`

`limit_user_id` is the global per-user limiter key. It should prefer QQ global user identity fields when QQ provides them, and fall back to member/user openid only when no global identity exists.

### Message Sending

All outgoing messages use QQ official HTTP OpenAPI:

- Group replies: `/v2/groups/{group_openid}/messages`
- C2C replies: `/v2/users/{user_openid}/messages`

The existing send behavior should be preserved:

- `Authorization: QQBot <access_token>`
- `X-Union-Appid`
- `msg_id`
- `msg_seq`
- URL sanitization
- 2000-character truncation
- reply-with-ads for normal replies
- ad-free `reply_plain`

OpenAPI send failures should be logged to the cloud log stream with:

- target type
- target id
- status code
- error body prefix
- triggering message id

## Cloud Data Model

The Control API owns the following tables.

### users

Stores known QQ users.

Fields:

- `id`
- `openid`
- `global_openid`
- `union_openid`
- `first_seen_at`
- `last_seen_at`
- `last_group_openid`
- `display_name`
- `is_banned`
- `ban_reason`
- `banned_until`
- `created_at`
- `updated_at`

Identity rule:

- `global_openid` is the preferred stable user key for limits.
- `openid` keeps the current event-specific QQ id.
- Existing JSON keys migrate into `openid` and may later be linked to `global_openid` after users speak again.

### email_bindings

Stores one active email binding per user key.

Fields:

- `id`
- `user_key`
- `email`
- `created_at`
- `updated_at`
- `created_by`

### roles

Stores admin and staff grants.

Fields:

- `id`
- `user_key`
- `role`: `admin` or `staff`
- `password_hash`
- `added_by`
- `created_at`
- `updated_at`
- `revoked_at`

Staff login state should not need permanent DB storage. A staff password proves access; the dashboard and bot can issue short-lived sessions.

### resource_limit_rules

Stores `/restrict` rules.

Fields:

- `id`
- `resource`: `163`, `4399`, or `nfa`
- `limit_count`
- `window_unit`: `min`, `hour`, `day`, `month`, `quarter`, or `year`
- `window_seconds`
- `enabled`
- `updated_by`
- `created_at`
- `updated_at`

Rules are global across all groups.

### resource_usage

Stores successful resource obtains.

Fields:

- `id`
- `user_key`
- `resource`
- `source_group_openid`
- `message_id`
- `created_at`

Limit checks count rows by `user_key`, `resource`, and `created_at >= now - window`.

`/resetLimit` deletes or archives `resource_usage` rows for all users, but does not remove `resource_limit_rules`.

### command_logs

Stores bot command attempts and outcomes.

Fields:

- `id`
- `event_type`
- `message_type`
- `group_openid`
- `user_key`
- `raw_content`
- `normalized_command`
- `handled`
- `result_status`
- `error_summary`
- `created_at`

### audit_logs

Stores admin operations from bot commands and dashboard actions.

Fields:

- `id`
- `actor_user_key`
- `action`
- `target_type`
- `target_key`
- `before_json`
- `after_json`
- `created_at`

### outbound_logs

Stores outgoing QQ send attempts.

Fields:

- `id`
- `target_type`
- `target_id`
- `message_id`
- `status_code`
- `success`
- `error_summary`
- `created_at`

## Control API

Use FastAPI because the repo is already Python-first and the bot can share request models and test helpers.

Authentication:

- Bot worker uses an internal `BOT_CONTROL_TOKEN`.
- Dashboard uses admin login sessions.
- Production should terminate TLS at nginx for `bot.miracle.vin`.

Core API groups:

- `POST /internal/events/seen`
- `GET /internal/users/{user_key}/state`
- `POST /internal/email-bindings`
- `DELETE /internal/email-bindings/{user_key}`
- `GET /internal/resource-limits/{resource}/check`
- `POST /internal/resource-usage`
- `POST /internal/resource-limits`
- `POST /internal/resource-limits/reset-usage`
- `POST /internal/logs/command`
- `POST /internal/logs/outbound`
- `GET /admin/users`
- `PATCH /admin/users/{user_key}`
- `GET /admin/resource-limits`
- `PATCH /admin/resource-limits/{resource}`
- `GET /admin/logs/commands`
- `GET /admin/logs/audit`
- `GET /admin/logs/outbound`

The bot worker should call the internal API through a small client module. If the Control API is temporarily unavailable, the bot should fail closed for protected resource obtain commands and reply with a short maintenance message instead of accidentally bypassing limits.

## Dashboard

Dashboard first screen should be an operations console, not a landing page.

Primary views:

- Overview
  - bot status
  - recent event count
  - QQ send failure count
  - resource usage today
  - current stock for NFA, 4399, 163
- Users
  - search by openid, global openid, email
  - view bound email
  - ban/unban
  - role grant/revoke
- Limits
  - view and edit `163`, `4399`, `nfa` rules
  - reset usage
  - see top users by usage
- Logs
  - command logs
  - outbound send logs
  - audit logs
- Settings
  - group whitelist
  - ad text
  - feature toggles

The dashboard should use a quiet operational UI: dense tables, filters, drawers/modals for edits, and clear status chips.

## Migration Plan

### Phase 1: Official QQ Runtime

Scope:

- Add a dedicated QQ gateway module.
- Prefer `botpy`; fall back to the existing manual WebSocket implementation if needed.
- Remove Koishi/webhook from the production runtime path.
- Keep existing local JSON storage for this phase.
- Preserve commands and current tests.
- Update systemd so production runs only the Python bot worker for QQ ingress.

Success criteria:

- Group @ messages work.
- C2C messages work.
- Full group message whitelist behavior still works where QQ provides full events.
- Replies send through QQ HTTP OpenAPI.
- `/163`, `/4399`, `/nfa`, `/restrict`, `/resetLimit`, `/bind`, `/ban`, `/unban`, `/admin`, and `/whois` still behave.
- Koishi service can remain installed but disabled.

### Phase 2: Cloud Control API and Database

Scope:

- Add FastAPI app.
- Add PostgreSQL schema and migrations.
- Add a bot-side control client.
- Replace JSON-backed admin, staff, banned, email, and resource limit state with API-backed state.
- Add one-time migration script from local JSON into PostgreSQL.

Success criteria:

- Restarting the bot does not affect limits or user state.
- The same user is limited globally across all groups.
- `/resetLimit` clears global usage.
- Admin changes are visible in the database and audit logs.
- If the control API is down, resource obtain commands do not bypass limits.

### Phase 3: Dashboard

Scope:

- Add dashboard frontend.
- Add admin APIs needed by the dashboard.
- Configure nginx for `https://bot.miracle.vin`.
- Add dashboard auth.

Success criteria:

- Admin can search users.
- Admin can ban/unban users.
- Admin can grant/revoke staff/admin roles.
- Admin can view and edit resource limits.
- Admin can reset limit usage.
- Admin can view command, outbound, and audit logs.

## Rollout and Rollback

Rollout should be incremental:

1. Deploy Phase 1 with local JSON state.
2. Disable `koishi-bridge`.
3. Keep `koishi-bridge.service` files for one rollback window.
4. Verify official WebSocket receives messages for at least one active group and one C2C test.
5. Deploy Control API and database.
6. Run migration script.
7. Switch bot state backend from `json` to `control_api`.
8. Deploy dashboard.

Rollback:

- Phase 1 rollback: re-enable Koishi bridge and disable official WS runtime if QQ official ingress fails.
- Phase 2 rollback: set state backend back to `json` and restart the bot.
- Phase 3 rollback: dashboard can be stopped without affecting the bot worker.

## Testing

Add tests for:

- QQ event adapter normalizes botpy/manual events into the same internal event object.
- Global `limit_user_id` selection prefers global identity.
- OpenAPI send client builds correct group and C2C requests.
- Control API limit checks block after the configured count and window.
- `/restrict` writes a cloud rule.
- `/resetLimit` clears usage and keeps rules.
- JSON migration imports email bindings, admins, staff, bans, and cooldown/restrict data.
- Bot fails closed when Control API is unavailable for protected resource commands.
- Dashboard admin APIs require authentication.

Existing tests should remain passing during Phase 1. Phase 2 tests should allow both JSON and Control API backends until the migration is complete.

## Operational Notes

Secrets should move out of `config.yaml` and into environment variables:

- `QQ_APP_ID`
- `QQ_APP_SECRET`
- `BOT_CONTROL_TOKEN`
- `DATABASE_URL`
- `DASHBOARD_SESSION_SECRET`
- upstream inventory API keys
- SMTP credentials

The deploy tarball should exclude:

- `.venv`
- `node_modules`
- `__pycache__`
- local logs
- local data backups unless intentionally migrating

Systemd services after full migration:

- `official-qqbot.service`
- `official-qqbot-api.service`
- optional frontend static hosting through nginx, or a dashboard node service if the frontend framework requires it

Koishi and NoneBot services should be disabled in production after Phase 1 succeeds.

## Non-Goals For The First Implementation

- Multi-bot tenant support.
- Fine-grained dashboard permissions beyond admin/staff.
- Live WebSocket dashboard log streaming.
- Rewriting all bot command handlers.
- Removing local JSON files before the migration has been verified.

## Open Decisions Resolved For This Design

- Ingress uses official QQ WebSocket, not webhook.
- Sending uses official HTTP OpenAPI.
- Limits are global per user across all groups.
- Cloud database is the source of truth after Phase 2.
- Dashboard is a separate control plane at `bot.miracle.vin`.
- The first implementation should stay incremental and preserve current bot behavior.
