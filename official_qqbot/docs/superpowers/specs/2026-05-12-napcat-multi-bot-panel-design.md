# NapCat Multi-Bot Panel Design

Date: 2026-05-12

## Goal

Extend the existing Node.js management panel so it can supervise two NapCat instances plus two NapCat-based Python bots:

- `qqbot`, which connects to NapCat OneBot WebSocket on `127.0.0.1:3001`.
- `only群bot`, which connects to NapCat OneBot WebSocket on `127.0.0.1:3002`.

The public panel should let an authenticated admin start and stop each process, see status and logs, and understand when a bot is waiting for NapCat login or a missing OneBot WebSocket port.

## Current Context

The existing `official_qqbot` panel has:

- A Node.js HTTP server under `server/`.
- Static frontend files under `web/`.
- Login/session support.
- A single `BotProcessManager` that starts, stops, and tails one Python process.

The two NapCat bots under `C:\Users\Administrator\Desktop\123` are Python bots with `bot.py` entrypoints. They read `config.yaml`, build an `Authorization: Bearer <token>` header, and connect to NapCat with `websockets.connect(...)`. They do not log into QQ by themselves.

Each NapCat instance is an upstream QQ login and OneBot provider. The bots should be treated as downstream services that depend on their matching NapCat instance being started and logged in.

## Recommended Approach

Use the current Node.js panel as the shared supervisor.

The panel will manage multiple services instead of only one:

- `official-bot`
- `napcat-qqbot`
- `qqbot`
- `napcat-only-group`
- `only-group-bot`

Each service gets an independent command, working directory, environment, stop timeout, status, and log buffer. The same authentication and static web server remain in place.

## Service Model

Add a generic process manager for configured services. A service config contains:

- `id`
- `name`
- `kind`, such as `python-bot` or `napcat`
- `command`
- `entry`
- `args`
- `cwd`
- `env`
- `stopTimeoutMs`
- Optional `health` checks, such as a TCP port probe.
- Optional `dependsOn`, used by the UI and API to warn before starting a bot when NapCat is unavailable.

The existing single-bot API can remain for backward compatibility, but the new panel should use service-oriented endpoints:

- `GET /api/status`
- `POST /api/services/:id/start`
- `POST /api/services/:id/stop`
- `GET /api/services/:id/logs`
- `GET /api/logs/stream`

## NapCat Login Flow

The panel will not reimplement NapCat QR login in the first version. It will:

- Start and stop each NapCat process separately.
- Show NapCat logs in the panel.
- Show a configured NapCat WebUI URL or local port hint.
- Detect whether the configured OneBot ports are listening.
- Mark bots as `blocked` or `waiting-for-napcat` when their target port is not reachable.

This keeps login inside NapCat's own WebUI and avoids coupling the panel to NapCat internals that may change. The two NapCat instances must use separate data directories, WebUI ports, OneBot configs, and tokens.

## Bot Startup Flow

When starting `qqbot` or `only群bot`:

1. The panel checks whether the configured OneBot WebSocket port for that bot's matching NapCat instance is listening.
2. If the port is unavailable, the API returns a clear warning and does not start the bot by default.
3. If the port is available, the panel starts the bot process with UTF-8 Python environment variables.
4. The UI updates logs and status for that bot independently.

This prevents a bot from entering a confusing reconnect loop when NapCat is stopped or not logged in.

## Frontend Changes

Replace the single Bot status area with a service dashboard:

- One card per service.
- Start and stop buttons per service.
- PID, uptime, last exit, and health state.
- Per-service log tabs or filters.
- A small NapCat section with WebUI link and OneBot port status.

The plugin list from the official bot panel can remain, but it should be visually separate from process supervision.

## Linux Deployment

The deployment target remains Linux-friendly:

- Node.js runs the panel.
- Python virtual environments run the Python bots.
- Each NapCat instance is started by a configured command.
- systemd keeps the panel alive.
- The panel binds to `0.0.0.0:8787`.
- Firewall/security group must allow TCP `8787`.

Only the panel port needs to be public. NapCat OneBot ports should remain bound to `127.0.0.1` unless there is a deliberate reason to expose them.

## Security

The public panel controls real processes and should require:

- A changed admin password.
- Strong session secret.
- Ideally HTTPS through a reverse proxy.
- OneBot tokens kept out of frontend responses.

The panel must never display full `config.yaml` secrets, API keys, or OneBot tokens.

## Testing

Use focused tests for:

- Generic service config loading.
- Service start/stop behavior.
- Status response shape for multiple services.
- Health probe states for open and closed ports.
- UI rendering of multiple service cards.

Manual verification should include:

- Panel starts on Windows.
- Existing official bot can still start/stop.
- Both NapCat services can be started/stopped from panel.
- Bot start is blocked when the OneBot port is closed.
- Bot starts when the corresponding OneBot port is open.
- Logs remain readable as UTF-8.
