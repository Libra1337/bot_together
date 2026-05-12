# Linux 部署说明

## 1. 准备环境

推荐 Ubuntu/Debian：

```bash
sudo apt update
sudo apt install -y python3 python3-venv nodejs npm nginx
```

Node.js 建议 20 或更新版本。把项目放到 `/opt/official_qqbot`：

```bash
sudo useradd -r -m -d /opt/official_qqbot qqbot
sudo mkdir -p /opt/official_qqbot
sudo cp -r . /opt/official_qqbot
sudo chown -R qqbot:qqbot /opt/official_qqbot
sudo chmod +x /opt/official_qqbot/scripts/*.sh
```

## 2. 首次启动

```bash
cd /opt/official_qqbot
sudo -u qqbot bash scripts/start-panel.sh
```

面板默认监听 `0.0.0.0:8787`，首次运行会生成 `data/panel.json`。

默认账号是：

```text
admin / admin123456
```

上线前必须修改 `data/panel.json` 里的用户密码。可以临时把用户写成明文密码，面板启动时会自动转成哈希：

```json
{
  "auth": {
    "users": [
      { "username": "admin", "password": "你的强密码", "role": "admin" }
    ]
  }
}
```

## 3. systemd 托管面板

```bash
sudo cp /opt/official_qqbot/deploy/qqbot-panel.service /etc/systemd/system/qqbot-panel.service
sudo systemctl daemon-reload
sudo systemctl enable --now qqbot-panel
sudo systemctl status qqbot-panel
```

面板进程由 systemd 托管，Bot 进程由面板里的“启动 Bot / 停止 Bot”按钮控制。

## 4. NapCat 多 Bot 面板

新版面板会在 `data/panel.json` 里生成 `services` 配置，默认包含：

- `official-bot`
- `napcat-qqbot`
- `qqbot`
- `napcat-only-group`
- `only-group-bot`

两个 NapCat 服务默认都是未配置状态，需要按服务器上的 NapCat 实际启动命令分别修改 `command`、`entry`、`args`、`cwd`，再把对应的 `disabled` 改成 `false`。

必须保持两套 NapCat 实例相互独立，因为两个 QQ 号需要不同登录态和不同 OneBot token：

- `napcat-qqbot`：给 `qqbot` 使用，OneBot WebSocket 端口是 `127.0.0.1:3001`。
- `napcat-only-group`：给 `only-group-bot` 使用，OneBot WebSocket 端口是 `127.0.0.1:3002`。

如果使用同一份 NapCat 程序目录，也要给两套实例配置不同的数据目录、WebUI 端口、OneBot 配置文件和 token。不要让两个实例共用同一个登录数据目录。

Windows 本地面板使用 `scripts/start-napcat-instance.ps1` 启动两个实例。该脚本会调用 `scripts/napcat-launcher.cjs`，自动创建：

- `data/napcat/qqbot`
- `data/napcat/only-group-bot`

并为两套实例分别写入 WebUI 和 OneBot 配置。首次使用源码版 NapCat 前，需要先在 NapCat 源码目录完成构建：

```powershell
cd C:\Users\Administrator\Documents\GitHub\NapCatQQ
pnpm install
pnpm build:shell
```

如果没有生成 `packages\napcat-shell\dist\napcat.mjs`，面板里点击 NapCat 启动后会在日志中提示先构建。

两个 NapCat bot 建议放在独立目录，例如：

```bash
sudo mkdir -p /opt/napcat_bots
sudo cp -r /path/to/qqbot /opt/napcat_bots/qqbot
sudo cp -r /path/to/only-group-bot /opt/napcat_bots/only-group-bot
sudo chown -R qqbot:qqbot /opt/napcat_bots
```

分别创建虚拟环境：

```bash
sudo -u qqbot bash -lc 'cd /opt/napcat_bots/qqbot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'
sudo -u qqbot bash -lc 'cd /opt/napcat_bots/only-group-bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'
```

面板会在启动 `qqbot` 前检查 `127.0.0.1:3001`，启动 `only-group-bot` 前检查 `127.0.0.1:3002`。如果对应 NapCat 实例没启动、没登录、或 OneBot WebSocket 端口没开，面板会阻止 bot 启动并显示等待状态。

只需要把面板端口 `8787` 开到公网。NapCat 的 OneBot 端口建议保持 `127.0.0.1`，不要开放到公网。

## 5. 公网访问建议

不要直接裸奔 HTTP 管理面板。建议用 Nginx/Caddy 反代 HTTPS，并只开放 443：

```nginx
server {
  listen 80;
  server_name your.domain.com;
  return 301 https://$host$request_uri;
}

server {
  listen 443 ssl http2;
  server_name your.domain.com;

  ssl_certificate /etc/letsencrypt/live/your.domain.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/your.domain.com/privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8787;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

如果用 Nginx 反代，可以把 `data/panel.json` 改成只监听本机：

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8787
  }
}
```

## 6. 插件说明

插件放在 `plugins/<插件ID>/plugin.json`。

Python 插件：

```json
{
  "id": "hello_python",
  "type": "python",
  "entry": "plugin.py",
  "commands": ["/hello"],
  "enabled": true
}
```

外部命令插件，例如 Node.js：

```json
{
  "id": "echo_node",
  "type": "external",
  "command": "node",
  "args": ["plugin.js"],
  "commands": ["/echo"],
  "enabled": true
}
```

外部插件从 stdin 接收 JSON 事件，从 stdout 输出 JSON：

```json
{ "handled": true, "reply": "回复内容" }
```

面板里的插件开关会写入 `data/plugins.json`，Bot 收到消息时读取该状态。

## 7. 敏感配置

当前项目的 QQ、AI、SMTP 密钥仍在 `config.yaml`。公网部署时至少执行：

```bash
chmod 600 config.yaml data/panel.json
```

更稳的做法是后续把密钥迁移到环境变量或 `.env` 文件，并确保不会提交到公开仓库。
