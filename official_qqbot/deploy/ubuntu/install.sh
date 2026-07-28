#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/official_qqbot}"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nodejs npm

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cd "$APP_DIR/koishi-bridge"
npm install

sudo mkdir -p /etc/official-qqbot
if [ ! -f /etc/official-qqbot/koishi-bridge.env ]; then
  sudo cp "$APP_DIR/deploy/ubuntu/koishi-bridge.env.example" /etc/official-qqbot/koishi-bridge.env
  echo "Edit /etc/official-qqbot/koishi-bridge.env before starting koishi-bridge."
fi

sudo cp "$APP_DIR/deploy/ubuntu/official-qqbot.service" /etc/systemd/system/official-qqbot.service
sudo cp "$APP_DIR/deploy/ubuntu/official-qqbot-api.service" /etc/systemd/system/official-qqbot-api.service
sudo cp "$APP_DIR/deploy/ubuntu/koishi-bridge.service" /etc/systemd/system/koishi-bridge.service
sudo cp "$APP_DIR/deploy/ubuntu/nonebot-bridge.service" /etc/systemd/system/nonebot-bridge.service
sudo systemctl daemon-reload

echo "Install complete."
echo "Next:"
echo "  sudo nano /etc/official-qqbot/koishi-bridge.env"
echo "  sudo systemctl enable --now official-qqbot-api"
echo "  sudo systemctl enable --now official-qqbot"
echo "Optional rollback bridge services remain installed but disabled by default:"
echo "  sudo systemctl enable --now koishi-bridge"
echo "  sudo systemctl enable --now nonebot-bridge"
