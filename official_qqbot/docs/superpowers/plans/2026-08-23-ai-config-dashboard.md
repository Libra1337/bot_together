# AI 对话配置页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Add an admin-only AI configuration page that tests, saves, and immediately activates an OpenAI-compatible API URL, API key, and model.

**Architecture:** Put YAML loading, validation, connectivity checks, atomic writes, and Bot restart/rollback in `control_api/ai_config.py`. Keep `control_api/app.py` responsible for authenticated dashboard routes, form handling, audit logging, and rendering the page. The Bot continues to read `config.yaml` at startup, so only `official-qqbot` is restarted after a successful save.

**Tech Stack:** Python 3.12, FastAPI, Starlette `TestClient`, `httpx`, PyYAML, unittest, inline HTML/CSS dashboard templates, systemd.

---

### Task 1: Add the AI configuration manager

**Files:**
- Create: `control_api/ai_config.py`
- Test: `tests/test_ai_config.py`

- [x] **Step 1: Write failing unit tests**

Cover these concrete behaviors:

```python
def test_load_masks_key_and_reads_ai_values():
    manager = AIConfigManager(config_path)
    assert manager.public_settings() == {
        "base_url": "https://api.example.test/v1",
        "model": "model-a",
        "api_key_configured": True,
        "api_key_masked": "sk-***7890",
    }

def test_validate_rejects_invalid_url_and_empty_model_or_key():
    assert "API 地址" in manager.validate(AISettings("ftp://bad", "m", "k"))
    assert "模型" in manager.validate(AISettings("https://api.example.test/v1", "", "k"))
    assert "Key" in manager.validate(AISettings("https://api.example.test/v1", "m", ""))

async def test_check_accepts_openai_compatible_response():
    response = FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
    manager = AIConfigManager(config_path, client_factory=FakeAsyncClient(response))
    assert await manager.check(AISettings(url, "model-a", "secret")) == (True, "连接成功")

def test_save_keeps_other_config_sections_and_empty_key_keeps_old_key():
    manager.save(AISettings(url, "model-b", "old-secret"))
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["bot"]["app_id"] == "app-1"
    assert saved["ai"] == {"base_url": url, "api_key": "old-secret", "model": "model-b"}

def test_restart_failure_can_restore_previous_bytes():
    snapshot = manager.save(new_settings)
    manager.restore(snapshot)
    assert config_path.read_bytes() == original_bytes
```

Use a temporary YAML file, fake async HTTP client, and injected command runner; do not call the real AI service or systemd.

- [x] **Step 2: Run the focused tests and verify the expected RED state**

Run:

```powershell
python -m unittest tests.test_ai_config -v
```

Expected: import or attribute failures because `control_api.ai_config` does not exist yet.

- [x] **Step 3: Implement the smallest manager API**

Implement a frozen `AISettings` dataclass with `base_url`, `model`, and `api_key` string fields. Implement `AIConfigManager` with these concrete methods: `load() -> AISettings` reads the YAML `ai` section; `public_settings() -> dict` returns base URL, model, `api_key_configured`, and a masked key; `validate(settings) -> str | None` returns the first Chinese validation error or `None`; `check(settings) -> tuple[bool, str]` performs the async connectivity check; `save(settings) -> bytes` atomically replaces the YAML and returns the original bytes; `restore(snapshot) -> None` atomically restores those bytes; and `restart_bot() -> tuple[bool, str]` runs the injected restart and active-status commands.

Use `urlparse` to accept only `http` and `https` URLs with a network location. Test `{base_url.rstrip('/')}/chat/completions` with a 15-second timeout, a one-token request, and the supplied model. Never include the API key or full provider response in returned messages. Write a temporary YAML file beside `config.yaml`, flush it, then use `os.replace`.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the same unittest command. Expected: all manager tests pass.

### Task 2: Add authenticated Dashboard routes and page

**Files:**
- Modify: `control_api/app.py`
- Test: `tests/test_dashboard_app.py`

- [x] **Step 1: Add failing route and rendering tests**

Add tests for:

```python
def test_ai_dashboard_requires_login():
    assert client.get("/dashboard/ai").headers["location"] == "/dashboard/login"

def test_ai_dashboard_contains_chinese_form_and_masked_key_after_login():
    login()
    response = client.get("/dashboard/ai")
    assert response.status_code == 200
    assert "AI 对话" in response.text
    assert "检测连接" in response.text
    assert "保存并重启" in response.text
    assert "sk-full-secret" not in response.text

def test_ai_test_route_does_not_save_config():
    login()
    with patch.object(manager, "check", new=AsyncMock(return_value=(True, "连接成功"))):
        response = client.post("/dashboard/ai/test", data=form)
    assert response.status_code == 200
    assert "连接成功" in response.text

def test_ai_save_route_checks_then_restarts_and_audits():
    login()
    with patch.object(manager, "check", new=AsyncMock(return_value=(True, "连接成功"))), \
         patch.object(manager, "save", return_value=b"old"), \
         patch.object(manager, "restart_bot", return_value=(True, "Bot 已重启")):
        response = client.post("/dashboard/ai/save", data=form)
    assert response.status_code == 200
    assert "Bot 已重启" in response.text

def test_ai_save_route_restores_when_restart_fails():
    login()
    with patch.object(manager, "check", new=AsyncMock(return_value=(True, "连接成功"))), \
         patch.object(manager, "save", return_value=b"old"), \
         patch.object(manager, "restore") as restore, \
         patch.object(manager, "restart_bot", return_value=(False, "Bot 重启失败")):
        client.post("/dashboard/ai/save", data=form)
    restore.assert_called_once_with(b"old")
```

- [x] **Step 2: Run the dashboard tests and verify RED**

Run:

```powershell
python -m unittest tests.test_dashboard_app -v
```

Expected: route or page assertions fail because the AI page is not registered.

- [x] **Step 3: Wire the manager into `create_app`**

Add an optional `config_path` argument without changing existing callers. Instantiate one `AIConfigManager`, store it on `app.state`, and register:

- `GET /dashboard/ai`: authenticated page render.
- `POST /dashboard/ai/test`: merge blank Key with the stored Key, test only, and render status.
- `POST /dashboard/ai/save`: test, save atomically, restart Bot, rollback on restart failure, audit only URL/model, and render status.

Add “AI 对话” to `_nav_link` entries and a dashboard quick card. Keep complete API keys out of form values, HTML, audit details, and exception text.

- [x] **Step 4: Add the page template using existing dashboard styles**

Create `_ai_page(manager, notice="", error="")` using the existing dashboard shell. Include labels for `API 地址`, `API Key`, and `模型名称`; a password input with placeholder `留空保持当前 Key`; a status summary; and two buttons with loading/disabled states. Use `aria-live="polite"` for result feedback and respect the existing 150-300ms transitions.

- [x] **Step 5: Run dashboard tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_dashboard_app -v
```

Expected: all dashboard tests pass.

### Task 3: Integrate startup and validate the full feature

**Files:**
- Modify: `control_api/app.py` only if integration fixes are needed
- Test: `tests/test_dashboard_app.py`, `tests/test_ai_config.py`

- [x] **Step 1: Run focused tests plus compile checks**

Run:

```powershell
python -m unittest tests.test_ai_config tests.test_dashboard_app -v
python -m py_compile control_api\ai_config.py control_api\app.py bot.py
```

Expected: all focused tests pass and compilation exits with code 0.

- [x] **Step 2: Run the complete test suite**

Run:

```powershell
python -m unittest discover -s tests -p 'test*.py'
```

Expected: no failures or errors.

- [x] **Step 3: Inspect the final diff and sensitive-data behavior**

Run:

```powershell
rg -n "dashboard/ai|AIConfigManager|api_key_masked|systemctl restart official-qqbot" control_api tests
git diff --check
```

Confirm the page never renders the full configured key and the restart command targets only `official-qqbot`.
