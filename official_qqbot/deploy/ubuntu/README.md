# Ubuntu Deployment

This deployment runs QQ HTTPS callback ingress in the Python worker by default, because some QQ Bot apps cannot disable webhook callbacks after configuring an HTTPS callback URL:

- `official-qqbot`: Python bot worker, QQ webhook listener, optional official WebSocket ingress, QQ HTTP OpenAPI replies.
- `official-qqbot-api`: dashboard, cloud state API, and public `/qq` proxy to the bot worker.
- `koishi-bridge`: optional rollback bridge, disabled in production.
- `nonebot-bridge`: optional rollback bridge, disabled in production.

## Install

Copy this repository to `/opt/official_qqbot`, then run:

```bash
cd /opt/official_qqbot
bash deploy/ubuntu/install.sh
```

Edit:

```bash
sudo nano /etc/official-qqbot/koishi-bridge.env
```

For AI chat, set:

```text
AI_BASE_URL=https://fisx-ai.guimc.ltd/v1
AI_MODEL=deepseek-v4-flash
AI_API_KEY=your-private-api-key
```

Start services:

```bash
sudo systemctl enable --now official-qqbot-api
sudo systemctl enable --now official-qqbot
sudo systemctl disable --now koishi-bridge nonebot-bridge
```

Check logs:

```bash
journalctl -u official-qqbot -f
journalctl -u official-qqbot-api -f
```

## Update Existing Non-Git Install

If `/opt/official_qqbot` was copied from a tarball or with `rsync`, it is not a git repository. In that case `git pull` inside `/opt/official_qqbot` will fail with `not a git repository`. Update from a temporary clone instead:

```bash
sudo apt-get update
sudo apt-get install -y git rsync

rm -rf /tmp/bot_together
git clone --depth 1 --branch main https://github.com/Libra1337/bot_together.git /tmp/bot_together

sudo systemctl stop official-qqbot official-qqbot-api || true
sudo cp -a /opt/official_qqbot /opt/official_qqbot.bak-$(date +%F-%H%M%S)

sudo rsync -a --delete \
  --exclude data \
  --exclude .venv \
  --exclude config.yaml \
  --exclude logs \
  /tmp/bot_together/official_qqbot/ /opt/official_qqbot/

cd /opt/official_qqbot
.venv/bin/python -m pip install -r requirements.txt
if [ -d koishi-bridge ]; then
  (cd koishi-bridge && npm install)
fi

sudo mkdir -p /etc/official-qqbot
if [ ! -f /etc/official-qqbot/koishi-bridge.env ]; then
  sudo cp deploy/ubuntu/koishi-bridge.env.example /etc/official-qqbot/koishi-bridge.env
fi

sudo cp deploy/ubuntu/official-qqbot.service /etc/systemd/system/
sudo cp deploy/ubuntu/official-qqbot-api.service /etc/systemd/system/
sudo cp deploy/ubuntu/koishi-bridge.service /etc/systemd/system/
sudo cp deploy/ubuntu/nonebot-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart official-qqbot-api official-qqbot
sudo systemctl status official-qqbot-api official-qqbot --no-pager
```

## Cloud Control API

The bot can keep users, roles, bans, email bindings, resource limits, usage, and logs in a database-backed control API.

Install dependencies first, then set these values in `/etc/official-qqbot/koishi-bridge.env`:

```text
DATABASE_URL=sqlite:////opt/official_qqbot/data/control.db
CONTROL_API_BASE_URL=http://127.0.0.1:9000
BOT_CONTROL_TOKEN=replace-with-bot-token
ADMIN_CONTROL_TOKEN=wiewie123
DASHBOARD_SESSION_SECRET=replace-with-long-random-session-secret
QQ_WEBHOOK_FORWARD_URL=http://127.0.0.1:8765/qq
```

Start the API as a service:

```bash
sudo systemctl enable --now official-qqbot-api
```

Or run it manually for debugging:

```bash
cd /opt/official_qqbot
set -a
. /etc/official-qqbot/koishi-bridge.env
set +a
.venv/bin/python -m control_api.app
```

Import existing local JSON state once:

```bash
cd /opt/official_qqbot
set -a
. /etc/official-qqbot/koishi-bridge.env
set +a
.venv/bin/python -m control_api.migrate_local_state
```

Production order:

```text
1. Start the control API.
2. Run the local JSON migration once.
3. Start official-qqbot with CONTROL_API_BASE_URL and BOT_CONTROL_TOKEN configured.
```

If `CONTROL_API_BASE_URL` is empty, the bot uses the existing local JSON files and `data/cooldowns.json`.

## Dashboard Domain

The dashboard is served by the control API at:

```text
http://127.0.0.1:9000/dashboard
```

Point `https://bot.miracle.vin` to it with nginx:

```nginx
server {
    listen 80;
    server_name bot.miracle.vin;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name bot.miracle.vin;

    ssl_certificate /etc/letsencrypt/live/bot.miracle.vin/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.miracle.vin/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Dashboard login uses `ADMIN_CONTROL_TOKEN`. Set a separate long random `DASHBOARD_SESSION_SECRET` for signed sessions.

Dashboard pages:

- `/dashboard`: control overview
- `/dashboard/ads`: bot ad management backed by `data/ads.json`
- `/dashboard/users`: user OpenID and email bindings
- `/dashboard/permissions`: admin and Staff roles
- `/dashboard/bans`: banned OpenID list
- `/dashboard/limits`: global 163/4399/nfa fetch limits
- `/dashboard/logs`: command, outbound, and audit logs
- `/dashboard/settings`: runtime and data source settings
- `/dashboard/ai`: chat AI API, key, and model settings
- `/dashboard/image-ai`: image generation API, key, model, size, and cooldown settings

## AI Image Generation

Configure image generation from `/dashboard/image-ai`. The page tests an OpenAI-compatible `POST /images/generations` request before saving and restarts only `official-qqbot` after a successful update. Values saved under `image_ai` in `config.yaml` take precedence over the optional `IMAGE_AI_*` environment fallbacks.

Users can request one image with `/生图 description` or a natural phrase such as `帮我画一张雨夜里的重庆`. Group and private messages send the generated result through the QQ rich-media API and share the per-user cooldown.

Optional environment fallbacks:

```text
IMAGE_AI_ENABLED=0
IMAGE_AI_BASE_URL=https://example.com/v1
IMAGE_AI_API_KEY=replace-with-image-ai-api-key
IMAGE_AI_MODEL=grok-imagine-1.0-fast
IMAGE_AI_SIZE=1024x1024
IMAGE_AI_COOLDOWN_SECONDS=60
```

## QQ Webhook Callback

If the QQ Bot admin console says HTTPS callback disables WebSocket callback, keep the QQ callback URL as:

```text
https://bot.miracle.vin/qq
```

Use this runtime mode:

```text
QQ_OFFICIAL_WS_ENABLED=0
QQ_BRIDGE_ENABLED=1
QQ_WEBHOOK_PATH=/qq
QQ_WEBHOOK_FORWARD_URL=http://127.0.0.1:8765/qq
```

Request flow:

```text
QQ platform -> nginx -> official-qqbot-api /qq -> official-qqbot 127.0.0.1:8765/qq
```

The same internal listener still accepts Koishi compatibility payloads at `/koishi/message`, but Koishi itself is not required for this webhook mode.

## Optional Bridge Rollback

Pure official WebSocket mode is still available only when the QQ admin console has no HTTPS callback enabled:

```text
QQ_OFFICIAL_WS_ENABLED=1
QQ_BRIDGE_ENABLED=0
```

If you temporarily roll back to the NoneBot bridge, use WebSocket mode:

```text
NONEBOT_DRIVER=~httpx+~websockets
NONEBOT_QQ_USE_WEBSOCKET=1
```

Keep `QQ_GROUP_WHITELIST` aligned with the `group_openid` reported in logs. Group @ and C2C events do not require the whitelist; non-@ group messages do.

To roll back to Koishi:

```bash
sudo systemctl disable --now nonebot-bridge
sudo systemctl enable --now koishi-bridge
sudo systemctl restart official-qqbot koishi-bridge
```

The Python bridge listens on:

```text
http://127.0.0.1:8765/koishi/message
http://127.0.0.1:8765/qq
```

Koishi and NoneBot forward messages there with `X-Bridge-Token` when the compatibility bridge is enabled.
