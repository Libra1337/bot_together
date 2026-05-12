#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-$(pwd)}"
PANEL_SRC="$BUNDLE_DIR/official_qqbot"
QQBOT_SRC="$BUNDLE_DIR/qqbot"
ONLY_GROUP_SRC="$BUNDLE_DIR/only-group-bot"
NAPCAT_SRC="$BUNDLE_DIR/NapCatQQ"

PANEL_DST="/opt/official_qqbot"
BOTS_DST="/opt/napcat_bots"
NAPCAT_DST="/opt/NapCatQQ"

require_dir() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo "missing directory: $dir" >&2
    exit 1
  fi
}

copy_dir_contents() {
  local src="$1"
  local dst="$2"
  mkdir -p "$dst"
  cp -a "$src"/. "$dst"/
}

if [ "$(id -u)" -ne 0 ]; then
  echo "please run as root" >&2
  exit 1
fi

require_dir "$PANEL_SRC"
require_dir "$QQBOT_SRC"
require_dir "$ONLY_GROUP_SRC"
require_dir "$NAPCAT_SRC"

if ! command -v node >/dev/null 2>&1; then
  echo "node is required. Install Node.js 22.13 or newer first." >&2
  exit 1
fi

NODE_VERSION_CHECK="$(node - 2>&1 <<'NODE'
const [major, minor, patch] = process.versions.node.split(".").map(Number);
const ok = major > 22 || (major === 22 && (minor > 13 || (minor === 13 && patch >= 0)));
if (!ok) {
  console.error(`Node.js 22.13 or newer is required, current version is ${process.versions.node}.`);
  process.exit(1);
}
process.stdout.write(process.versions.node);
NODE
)" || {
  echo "$NODE_VERSION_CHECK" >&2
  exit 1
}
echo "Using Node.js $NODE_VERSION_CHECK"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install python3 and python3-venv first." >&2
  exit 1
fi

if ! ldconfig -p 2>/dev/null | grep -q 'libgnutls\.so\.30'; then
  echo "libgnutls.so.30 is required for Linux QQ/NapCat. Install libgnutls30 first." >&2
  exit 1
fi

useradd -r -m -d "$PANEL_DST" qqbot 2>/dev/null || true

systemctl stop qqbot-panel 2>/dev/null || true

copy_dir_contents "$PANEL_SRC" "$PANEL_DST"
copy_dir_contents "$QQBOT_SRC" "$BOTS_DST/qqbot"
copy_dir_contents "$ONLY_GROUP_SRC" "$BOTS_DST/only-group-bot"
copy_dir_contents "$NAPCAT_SRC" "$NAPCAT_DST"

if ! grep -q '^dangerouslyAllowAllBuilds:[[:space:]]*true[[:space:]]*$' "$NAPCAT_DST/pnpm-workspace.yaml"; then
  printf '\ndangerouslyAllowAllBuilds: true\n' >> "$NAPCAT_DST/pnpm-workspace.yaml"
fi

chown -R qqbot:qqbot "$PANEL_DST" "$BOTS_DST" "$NAPCAT_DST"
chmod +x "$PANEL_DST"/scripts/*.sh
chmod +x "$PANEL_DST"/deploy/*.sh

if [ -f "$PANEL_DST/config.yaml" ]; then
  chmod 600 "$PANEL_DST/config.yaml"
fi
if [ -f "$PANEL_DST/data/panel.json" ]; then
  chmod 600 "$PANEL_DST/data/panel.json"
fi

echo "Installing NapCat dependencies and building shell bundle..."
sudo -u qqbot -H env PATH="$PATH" bash <<EOF
set -euo pipefail
cd "$NAPCAT_DST"
if command -v corepack >/dev/null 2>&1; then
  corepack pnpm install --dangerously-allow-all-builds
  corepack pnpm build:shell
elif command -v pnpm >/dev/null 2>&1; then
  pnpm install --dangerously-allow-all-builds
  pnpm build:shell
elif command -v npm >/dev/null 2>&1; then
  npm exec --yes pnpm -- install --dangerously-allow-all-builds
  npm exec --yes pnpm -- build:shell
else
  echo "pnpm, corepack, or npm is required to install NapCat dependencies." >&2
  exit 1
fi
EOF

sudo -u qqbot bash -lc "cd '$PANEL_DST' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
sudo -u qqbot bash -lc "cd '$BOTS_DST/qqbot' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
sudo -u qqbot bash -lc "cd '$BOTS_DST/only-group-bot' && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

cp "$PANEL_DST/deploy/qqbot-panel.service" /etc/systemd/system/qqbot-panel.service
systemctl daemon-reload
systemctl enable --now qqbot-panel

if command -v ufw >/dev/null 2>&1; then
  ufw allow 8787/tcp || true
fi

echo "Panel status:"
systemctl --no-pager --full status qqbot-panel || true
echo
echo "Local check:"
TARGET_URL="http://127.0.0.1:8787/" node - <<'NODE'
const http = require("node:http");
const https = require("node:https");

const target = process.env.TARGET_URL;
const client = target.startsWith("https:") ? https : http;

function probe() {
  return new Promise((resolve) => {
    const req = client.request(
      target,
      { method: "HEAD", timeout: 5000 },
      (res) => {
        res.resume();
        resolve({ ok: true, statusCode: res.statusCode });
      }
    );
    req.on("error", (error) => resolve({ ok: false, error }));
    req.on("timeout", () => {
      req.destroy(new Error("timeout"));
    });
    req.end();
  });
}

async function main() {
  const attempts = 60;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const result = await probe();
    if (result.ok) {
      console.log(`HTTP ${result.statusCode}`);
      process.exit(0);
    }
    if (attempt === attempts) {
      console.error(result.error.message);
      process.exit(1);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
NODE
