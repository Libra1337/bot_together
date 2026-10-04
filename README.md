# bot_together

Linux deployment bundle for the management panel, two NapCat-backed bots, and NapCatQQ source.

## Layout

- `official_qqbot/` - management panel and official bot
- `qqbot/` - first NapCat bot
- `only-group-bot/` - second NapCat bot
- `NapCatQQ/` - NapCat source used by the launcher

## Deploy On Linux

For the official bot and management panel, clone this repository, then run:

```bash
sudo mkdir -p /opt/official_qqbot
sudo cp -a bot_together/official_qqbot/. /opt/official_qqbot/
cd /opt/official_qqbot
cp -n config.example.yaml config.yaml
bash deploy/ubuntu/install.sh
```

Runtime secrets and local state are intentionally not committed. Keep existing `config.yaml` files on the server, or create them under:

- `/opt/official_qqbot/config.yaml`
- `/opt/napcat_bots/qqbot/config.yaml`
- `/opt/napcat_bots/only-group-bot/config.yaml`

Optional 4399 Sauth secrets should be supplied through environment variables: `SAUTH_API_KEY` and `SAUTH_ADMIN_TOKEN`.

See [official deployment instructions](official_qqbot/deploy/ubuntu/README.md) for configuration and services. The two NapCat bot directories and NapCatQQ are source components; this repository does not currently contain a combined Linux installer.

## Self-check

With Python 3.11+ and Node.js installed:

```bash
python -m pip install -r official_qqbot/requirements.txt
cd official_qqbot/koishi-bridge
npm ci
cd ../..
python official_qqbot/run_tests.py
python -m compileall -q official_qqbot qqbot only-group-bot
```

The test runner uses a temporary copy with sample configuration and disposable data, so it does not read or modify production credentials/state. NapCatQQ has separate checks: `pnpm install --frozen-lockfile`, `pnpm typecheck`, and `pnpm --filter napcat-test exec vitest run` in its directory.
