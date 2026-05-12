# bot_together

Linux deployment bundle for the management panel, two NapCat-backed bots, and NapCatQQ source.

## Layout

- `official_qqbot/` - management panel and official bot
- `qqbot/` - first NapCat bot
- `only-group-bot/` - second NapCat bot
- `NapCatQQ/` - NapCat source used by the launcher

## Deploy On Linux

Clone this repository, then run:

```bash
cd bot_together
bash official_qqbot/deploy/install-linux-bundle.sh "$PWD"
```

Runtime secrets and local state are intentionally not committed. Keep existing `config.yaml` files on the server, or create them under:

- `/opt/official_qqbot/config.yaml`
- `/opt/napcat_bots/qqbot/config.yaml`
- `/opt/napcat_bots/only-group-bot/config.yaml`

Optional 4399 Sauth secrets should be supplied through environment variables: `SAUTH_API_KEY` and `SAUTH_ADMIN_TOKEN`.
