# Phase 1 Official QQ Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production default runtime use QQ official WebSocket for event ingress and QQ HTTP OpenAPI for replies, with Koishi/NoneBot bridges disabled by default.

**Architecture:** Keep the existing Python bot worker as the only production message runtime in Phase 1. Preserve local JSON state and existing command handlers, but change runtime configuration, deployment defaults, and tests so `official-qqbot.service` runs the official WebSocket path and the local bridge listener is opt-in only.

**Tech Stack:** Python 3.12, `asyncio`, `websockets`, `httpx`, `aiohttp` for optional bridge compatibility, `unittest`, systemd deployment files.

---

## File Structure

- Modify `C:\Users\Administrator\Desktop\official_qqbot\bot.py`
  - Add an environment override for `BRIDGE_ENABLED`.
  - Log bridge status during startup.
  - Keep official WebSocket as the default QQ ingress path.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\config.yaml`
  - Add explicit `official_ws_enabled: true`.
  - Change `bridge.enabled` to `false`.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\koishi-bridge.env.example`
  - Set `QQ_OFFICIAL_WS_ENABLED=1`.
  - Add `QQ_BRIDGE_ENABLED=0`.
  - Keep Koishi/NoneBot variables documented as compatibility values.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\install.sh`
  - Keep installing bridge files for rollback.
  - Change final instructions to start only `official-qqbot`.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\README.md`
  - Document official-only production mode.
  - Document rollback commands for Koishi or NoneBot.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_official_runtime_defaults.py`
  - Verify config defaults and deployment env defaults select official WebSocket and disable the Python bridge listener.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\tests\test_runtime_tasks.py`
  - Add coverage for official-only runtime task selection.

## Task 1: Runtime Defaults

**Files:**

- Modify: `C:\Users\Administrator\Desktop\official_qqbot\bot.py`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\config.yaml`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_official_runtime_defaults.py`

- [ ] **Step 1: Write failing tests for official runtime defaults**

Create `tests/test_official_runtime_defaults.py` with:

```python
import os
import unittest

import yaml


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OfficialRuntimeDefaultsTests(unittest.TestCase):
    def test_config_defaults_to_official_websocket_without_bridge_listener(self):
        with open(os.path.join(ROOT, "config.yaml"), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.assertIs(config["bot"].get("official_ws_enabled"), True)
        self.assertIs(config["bridge"].get("enabled"), False)

    def test_deploy_env_defaults_to_official_websocket(self):
        path = os.path.join(ROOT, "deploy", "ubuntu", "koishi-bridge.env.example")
        with open(path, "r", encoding="utf-8") as f:
            env = f.read()

        self.assertIn("QQ_OFFICIAL_WS_ENABLED=1", env)
        self.assertIn("QQ_BRIDGE_ENABLED=0", env)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the default tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_official_runtime_defaults -v
```

Expected before implementation:

```text
FAIL: test_config_defaults_to_official_websocket_without_bridge_listener
FAIL: test_deploy_env_defaults_to_official_websocket
```

- [ ] **Step 3: Change runtime config defaults**

In `config.yaml`, set:

```yaml
bot:
  official_ws_enabled: true

bridge:
  enabled: false
```

Keep the existing `app_id`, `app_secret`, token, group whitelist, host, port, and token values unchanged.

- [ ] **Step 4: Add bridge environment override in `bot.py`**

Replace the current bridge enabled assignment with:

```python
BRIDGE_ENABLED = _config_bool(BRIDGE_CONFIG, "enabled", "QQ_BRIDGE_ENABLED", False)
```

Add this startup log line after the official WebSocket log:

```python
_log.info(f"Bridge listener enabled: {BRIDGE_ENABLED}")
```

- [ ] **Step 5: Run tests for default behavior**

Run:

```powershell
python -m unittest tests.test_official_runtime_defaults -v
```

Expected:

```text
OK
```

## Task 2: Runtime Task Selection

**Files:**

- Modify: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_runtime_tasks.py`

- [ ] **Step 1: Add official-only runtime task test**

Add this test method to `RuntimeTaskTests`:

```python
    def test_official_runtime_uses_websocket_without_bridge_by_default(self):
        old_ws = bot.run_websocket
        old_token = bot.token_refresh_loop
        old_bridge = bot.run_koishi_bridge_server
        bot.run_websocket = lambda: "ws"
        bot.token_refresh_loop = lambda: "token"
        bot.run_koishi_bridge_server = lambda: "bridge"
        try:
            tasks = bot._build_runtime_tasks(official_ws_enabled=True, bridge_enabled=False)

            self.assertEqual(tasks, ["ws", "token"])
        finally:
            bot.run_websocket = old_ws
            bot.token_refresh_loop = old_token
            bot.run_koishi_bridge_server = old_bridge
```

- [ ] **Step 2: Run the runtime task tests**

Run:

```powershell
python -m unittest tests.test_runtime_tasks -v
```

Expected:

```text
OK
```

## Task 3: Deployment Defaults

**Files:**

- Modify: `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\koishi-bridge.env.example`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\install.sh`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\README.md`

- [ ] **Step 1: Update environment example**

Set these lines in `deploy/ubuntu/koishi-bridge.env.example`:

```text
QQ_OFFICIAL_WS_ENABLED=1
QQ_BRIDGE_ENABLED=0
```

Keep the Koishi and NoneBot variables below them so rollback remains possible.

- [ ] **Step 2: Update install script final instructions**

Replace the final startup guidance in `deploy/ubuntu/install.sh` with:

```bash
echo "Install complete."
echo "Next:"
echo "  sudo nano /etc/official-qqbot/koishi-bridge.env"
echo "  sudo systemctl enable --now official-qqbot"
echo "Optional rollback bridge services remain installed but disabled by default:"
echo "  sudo systemctl enable --now koishi-bridge"
echo "  sudo systemctl enable --now nonebot-bridge"
```

- [ ] **Step 3: Update deployment README**

Rewrite the opening service description to state:

```markdown
This deployment runs official QQ ingress in the Python worker by default:

- `official-qqbot`: Python bot worker, QQ official WebSocket ingress, QQ HTTP OpenAPI replies.
- `koishi-bridge`: optional rollback bridge, disabled in production.
- `nonebot-bridge`: optional rollback bridge, disabled in production.
```

Set the start commands to:

```bash
sudo systemctl enable --now official-qqbot
sudo systemctl disable --now koishi-bridge nonebot-bridge
```

Add rollback commands:

```bash
sudo systemctl disable --now nonebot-bridge
sudo systemctl enable --now koishi-bridge
sudo systemctl restart official-qqbot koishi-bridge
```

- [ ] **Step 4: Run deployment default tests**

Run:

```powershell
python -m unittest tests.test_official_runtime_defaults -v
```

Expected:

```text
OK
```

## Task 4: Full Verification

**Files:**

- Verify: all Python files and tests.

- [ ] **Step 1: Compile touched Python files**

Run:

```powershell
python -m py_compile bot.py shared_cooldown.py handlers/sauth.py adapters/qq_official.py adapters/koishi_bridge.py adapters/nonebot_bridge.py
```

Expected:

```text
No output and exit code 0.
```

- [ ] **Step 2: Run the complete Python test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected:

```text
All tests pass.
```

- [ ] **Step 3: Check Koishi plugin syntax remains valid**

Run:

```powershell
node --check koishi-bridge/plugins/python-bridge/index.js
```

Expected:

```text
No output and exit code 0.
```

- [ ] **Step 4: Summarize deployment commands**

Use these server commands after packaging:

```bash
cd /opt/official_qqbot
systemctl disable --now koishi-bridge nonebot-bridge || true
systemctl enable --now official-qqbot
systemctl restart official-qqbot
journalctl -u official-qqbot -n 120 --no-pager
```

Expected:

```text
official-qqbot starts, logs show Official WS enabled: True, Bridge listener enabled: False, and QQ WebSocket connects.
```

## Self-Review

- Spec coverage: This plan covers Phase 1 from the design spec. It does not implement the cloud Control API or dashboard because those are Phase 2 and Phase 3.
- Placeholder scan: No `TODO`, `TBD`, or unspecified implementation steps are present.
- Type consistency: The runtime flag names are `QQ_OFFICIAL_WS_ENABLED` and `QQ_BRIDGE_ENABLED`; the code variable names are `OFFICIAL_WS_ENABLED` and `BRIDGE_ENABLED`; runtime task parameters are `official_ws_enabled` and `bridge_enabled`.
