# AI Image Generation Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore OpenAI-compatible image generation in Official QQBot and add a secure standalone dashboard page for configuring and testing it.

**Architecture:** Keep image generation independent from chat AI. A focused runtime client handles intent parsing and `/images/generations`; a focused dashboard manager owns `image_ai` YAML persistence and connectivity checks; `bot.py` only orchestrates routing, cooldown, and QQ rich-media delivery.

**Tech Stack:** Python 3.12+, `httpx`, FastAPI, PyYAML, `unittest`, QQ Official Bot v2 HTTP API

---

### Task 1: Image generation runtime client

**Files:**
- Create: `handlers/image_gen.py`
- Create: `tests/test_image_gen.py`

- [ ] **Step 1: Write failing request parsing and API tests**

Cover explicit `/生图` prompts, old natural-language phrases, ordinary text rejection, URL responses, `b64_json` responses, timeout, non-2xx responses, and missing image data. Use a capture `httpx.AsyncClient` replacement and assert the request target is `{base_url}/images/generations` with `model`, `prompt`, `n: 1`, and `size`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_image_gen -v`

Expected: import failure because `handlers.image_gen` does not exist.

- [ ] **Step 3: Implement the focused client**

Create:

```python
@dataclass(frozen=True)
class GeneratedImage:
    url: str = ""
    b64_json: str = ""

class ImageGenerator:
    async def generate(self, prompt: str) -> tuple[GeneratedImage | None, str]: ...

def is_image_request(content: str) -> bool: ...
def extract_image_prompt(content: str) -> str: ...
```

Use `httpx.AsyncClient(timeout=90.0)`, Bearer authentication, bounded error messages, and never log response bodies or Base64 image content.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_image_gen -v`

Expected: all image generation client tests pass.

### Task 2: Dashboard image AI configuration manager

**Files:**
- Create: `control_api/image_ai_config.py`
- Create: `tests/test_image_ai_config.py`

- [ ] **Step 1: Write failing configuration tests**

Define the desired settings object:

```python
@dataclass(frozen=True)
class ImageAISettings:
    enabled: bool
    base_url: str
    model: str
    api_key: str
    size: str
    cooldown_seconds: int
```

Test YAML loading, masked public values, URL/model/Key/size/cooldown validation, real image check for URL and Base64 responses, atomic save preserving unrelated YAML sections, restore, and Bot restart status checks.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_image_ai_config -v`

Expected: import failure because `control_api.image_ai_config` does not exist.

- [ ] **Step 3: Implement the manager**

Add `ImageAIConfigManager` with `load`, `public_settings`, `validate`, `check`, `save`, `restore`, and `restart_bot`. Restrict `size` to `1024x1024`, `1024x1536`, and `1536x1024`; require cooldown from 0 through 86400 seconds; perform atomic file replacement; return a preview data URI for Base64 or an escaped URL value for URL output.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_image_ai_config -v`

Expected: all image configuration tests pass.

### Task 3: QQ rich-media image delivery

**Files:**
- Modify: `bot.py`
- Create: `tests/test_image_sending.py`

- [ ] **Step 1: Write failing QQ payload tests**

Test group upload to `/v2/groups/{group_openid}/files`, C2C upload to `/v2/users/{user_openid}/files`, URL payload using `url`, Base64 payload using `file_data`, `file_type: 1`, `srv_send_msg: false`, and final message payload:

```python
{
    "msg_type": 7,
    "media": {"file_info": "..."},
    "msg_id": "...",
    "msg_seq": 1,
}
```

Also test upload failure, missing `file_info`, and final-send failure without leaking image content.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_image_sending -v`

Expected: failure because the image reply helpers do not exist.

- [ ] **Step 3: Implement image upload and send helpers**

Add `_build_media_upload_payload`, `_build_media_message_payload`, `_send_image`, and `reply_image`. Reuse `get_auth_header`, `_next_msg_seq`, `_status_ok`, `API_BASE`, and `_log_outbound_event`; use a longer upload timeout and log only HTTP status plus short error category.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_image_sending -v`

Expected: all QQ image delivery tests pass.

### Task 4: Bot configuration, cooldown, and message routing

**Files:**
- Modify: `bot.py`
- Create: `tests/test_image_routing.py`
- Modify: `tests/test_config_env.py`

- [ ] **Step 1: Write failing runtime and routing tests**

Test that `image_ai` YAML values override legacy `IMAGE_AI_*` environment values, missing YAML values fall back to environment values, `/生图` without a prompt shows usage, disabled/unconfigured states never call upstream, natural-language requests bypass `AIChat`, successful generation calls `reply_image`, and `limit_user_id` shares one cooldown between group and C2C contexts.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_image_routing tests.test_config_env -v`

Expected: image routing assertions fail while existing configuration tests remain green.

- [ ] **Step 3: Wire configuration and routing**

Load `IMAGE_AI_CONFIG = config.get("image_ai", {})`, normalize its fields with YAML-first lookup, construct one `ImageGenerator`, and add an in-memory monotonic cooldown map keyed by `ctx.get("limit_user_id") or ctx["user_openid"]`. Call the image handler after weather/link handling and before fuzzy matching and normal AI chat. Add `/生图 描述` to help text.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_image_routing tests.test_config_env -v`

Expected: all routing and configuration tests pass.

### Task 5: Standalone AI image dashboard page

**Files:**
- Modify: `control_api/app.py`
- Modify: `tests/test_dashboard_app.py`

- [ ] **Step 1: Write failing dashboard tests**

Test unauthenticated redirects for `/dashboard/image-ai`, Chinese form labels and masked Key rendering, test requests that do not save, successful save/restart/audit behavior, failed restart rollback, failed writes, preview rendering for URL and Base64, and audit detail that includes only base URL/model/size/cooldown/enabled.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_dashboard_app.DashboardAppTests.test_image_ai_dashboard_requires_login tests.test_dashboard_app.DashboardAppTests.test_image_ai_dashboard_contains_chinese_form -v`

Expected: 404 or missing method failures.

- [ ] **Step 3: Implement routes and page**

Attach `ImageAIConfigManager` to app state and add GET `/dashboard/image-ai`, POST `/dashboard/image-ai/test`, and POST `/dashboard/image-ai/save`. Add “AI 生图” to the sidebar, use an accessible checkbox, labeled inputs, a size select, numeric cooldown input, masked Key status, preview area, loading button behavior, and current Dashboard spacing/transition classes.

- [ ] **Step 4: Run dashboard tests and verify GREEN**

Run: `python -m unittest tests.test_dashboard_app -v`

Expected: all Dashboard tests pass.

### Task 6: Documentation and deployment defaults

**Files:**
- Modify: `deploy/ubuntu/koishi-bridge.env.example`
- Modify: `deploy/ubuntu/README.md`

- [ ] **Step 1: Document optional environment fallbacks**

Add `IMAGE_AI_ENABLED`, `IMAGE_AI_BASE_URL`, `IMAGE_AI_API_KEY`, `IMAGE_AI_MODEL`, `IMAGE_AI_SIZE`, and `IMAGE_AI_COOLDOWN_SECONDS` to the example without real credentials. Document `/dashboard/image-ai`, `/生图 描述`, natural-language triggers, and that Dashboard YAML values take precedence.

- [ ] **Step 2: Verify documentation and secrets**

Run: `git diff --check` and `rg -n "sk-[A-Za-z0-9]{16,}" official_qqbot`

Expected: no whitespace errors and no newly introduced real keys.

### Task 7: Full verification, commit, push, and deploy

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run the full test suite and compile check**

Run: `python -m unittest discover -s tests` and `python -m py_compile bot.py handlers/image_gen.py control_api/image_ai_config.py control_api/app.py`.

Expected: all tests pass and compilation exits zero.

- [ ] **Step 2: Review the final diff**

Run: `git diff --check`, `git status --short`, and `git diff --stat HEAD~1`.

Expected: only scoped source, test, and documentation changes.

- [ ] **Step 3: Commit and push**

Commit with user identity `Libra1337 <Christianwu1020@outlook.com>` and push `main` to `https://github.com/Libra1337/bot_together.git` using HTTP/1.1 retry if Schannel drops the first connection.

- [ ] **Step 4: Deploy without overwriting runtime data**

Back up `/opt/official_qqbot`, upload the verified `official_qqbot` tree, and extract over `/opt/official_qqbot` while preserving `config.yaml`, `data`, `.venv`, and `logs`. Restart `official-qqbot-api` and `official-qqbot`.

- [ ] **Step 5: Verify production behavior**

Check both services are active, `/dashboard/image-ai` redirects when unauthenticated, existing `/qq` webhook still returns success, startup logs contain no traceback, the existing admin password remains `wiewie123`, and the Bot reports the image generation enabled/configured state without exposing the Key.

