# Phase 2 Cloud Control API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cloud control API and database-backed state layer for users, roles, email bindings, resource limits, usage, and logs, then wire the bot to use that backend when configured.

**Architecture:** Build a small Python control plane with SQLAlchemy models and a FastAPI app. Keep the bot-side state access behind one backend interface so the local JSON path still works during development, while the cloud backend can be switched on with `CONTROL_API_BASE_URL` and `BOT_CONTROL_TOKEN`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, httpx, sqlite for tests, PostgreSQL via `DATABASE_URL`, unittest.

---

## File Structure

- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\__init__.py`
  - Package marker.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\db.py`
  - Engine, session factory, and schema initialization.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\models.py`
  - SQLAlchemy ORM models.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\schemas.py`
  - Pydantic request and response models.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\service.py`
  - Database operations for users, bindings, roles, limits, usage, and logs.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\auth.py`
  - Token guards for internal and admin routes.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\app.py`
  - FastAPI app factory and route registration.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\client.py`
  - Sync HTTP client used by the bot backend.
- Create `C:\Users\Administrator\Desktop\official_qqbot\control_api\migrate_local_state.py`
  - One-time migration from local JSON files into the database.
- Create `C:\Users\Administrator\Desktop\official_qqbot\state_backend.py`
  - Local and cloud-backed state adapters used by `bot.py`.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\bot.py`
  - Route admin, staff, ban, email, and resource-limit operations through the backend interface.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\requirements.txt`
  - Add FastAPI, SQLAlchemy, and the database driver.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\koishi-bridge.env.example`
  - Add control API and database environment variables.
- Modify `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\README.md`
  - Document cloud control API startup and migration flow.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_service.py`
  - Exercise SQLAlchemy service methods directly.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_app.py`
  - Exercise the FastAPI routes and auth guards.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_migration.py`
  - Exercise migration from local JSON into the DB.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_client.py`
  - Exercise the bot-side HTTP client against a mock transport.
- Create `C:\Users\Administrator\Desktop\official_qqbot\tests\test_state_backend.py`
  - Exercise the local and cloud backend selection logic.

## Task 1: Database And Service Layer

**Files:**

- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\__init__.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\db.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\models.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\schemas.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\service.py`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_service.py`

- [ ] **Step 1: Write the failing service tests**

Create `tests/test_control_api_service.py` with:

```python
import tempfile
import unittest

from control_api.db import create_app_engine, init_db, session_scope
from control_api.service import ControlService


class ControlApiServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_app_engine(f"sqlite:///{self.tmp.name}/control.db")
        init_db(self.engine)
        self.service = ControlService(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_set_rule_check_usage_and_reset(self):
        self.service.set_resource_limit("163", 1, "day", updated_by="admin")
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))

        self.service.record_resource_usage(
            "163", "user-a", source_group_openid="group-1", message_id="msg-1"
        )
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertTrue(blocked)
        self.assertEqual((count, limit, window), (1, 1, 86400))

        self.service.reset_resource_usage()
        blocked, count, limit, window = self.service.check_resource_limit(
            "163", "user-a"
        )
        self.assertFalse(blocked)
        self.assertEqual((count, limit, window), (0, 1, 86400))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the service tests and confirm they fail**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_service -v
```

Expected before implementation:

```text
ModuleNotFoundError for control_api
```

- [ ] **Step 3: Implement the database and service layer**

Create SQLAlchemy models for:

```python
users
email_bindings
roles
resource_limit_rules
resource_usage
command_logs
audit_logs
outbound_logs
```

Implement these service methods with SQLAlchemy sessions:

```python
class ControlService:
    def upsert_seen_user(...)
    def get_user_state(...)
    def set_email_binding(...)
    def delete_email_binding(...)
    def add_role(...)
    def revoke_role(...)
    def list_roles(...)
    def set_resource_limit(...)
    def get_resource_limit(...)
    def check_resource_limit(...)
    def record_resource_usage(...)
    def reset_resource_usage(...)
    def log_command(...)
    def log_audit(...)
    def log_outbound(...)
```

Use `sqlite` for tests and `DATABASE_URL` for production.

- [ ] **Step 4: Run the service tests again**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_service -v
```

Expected:

```text
OK
```

## Task 2: FastAPI App And Auth

**Files:**

- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\auth.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\app.py`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_app.py`

- [ ] **Step 1: Write the failing FastAPI route tests**

Create `tests/test_control_api_app.py` with:

```python
import tempfile
import unittest

from fastapi.testclient import TestClient

from control_api.app import create_app


class ControlApiAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(
            database_url=f"sqlite:///{self.tmp.name}/control.db",
            bot_token="bot-token",
            admin_token="admin-token",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_internal_limit_route_requires_bot_token(self):
        resp = self.client.get("/internal/resource-limits/163/check?user_key=user-a")
        self.assertEqual(resp.status_code, 401)

        resp = self.client.get(
            "/internal/resource-limits/163/check?user_key=user-a",
            headers={"X-Bot-Token": "bot-token"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_set_and_check_limit_through_api(self):
        self.client.post(
            "/internal/resource-limits",
            headers={"X-Bot-Token": "bot-token"},
            json={"resource": "163", "limit_count": 1, "window_unit": "day"},
        )
        resp = self.client.get(
            "/internal/resource-limits/163/check?user_key=user-a",
            headers={"X-Bot-Token": "bot-token"},
        )
        self.assertEqual(resp.json()["blocked"], False)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the FastAPI tests and confirm they fail**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_app -v
```

Expected before implementation:

```text
ModuleNotFoundError for fastapi or control_api
```

- [ ] **Step 3: Implement FastAPI app and auth guards**

Implement:

```python
def create_app(database_url: str, bot_token: str, admin_token: str) -> FastAPI:
    ...
```

Add these routes:

```python
POST /internal/events/seen
GET /internal/users/{user_key}/state
POST /internal/email-bindings
DELETE /internal/email-bindings/{user_key}
GET /internal/resource-limits/{resource}/check
POST /internal/resource-usage
POST /internal/resource-limits
POST /internal/resource-limits/reset-usage
POST /internal/logs/command
POST /internal/logs/outbound
GET /admin/users
PATCH /admin/users/{user_key}
GET /admin/resource-limits
PATCH /admin/resource-limits/{resource}
GET /admin/logs/commands
GET /admin/logs/audit
GET /admin/logs/outbound
```

Protect internal routes with `X-Bot-Token` and admin routes with `X-Admin-Token`.

- [ ] **Step 4: Run the FastAPI tests again**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_app -v
```

Expected:

```text
OK
```

## Task 3: Local JSON Migration

**Files:**

- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\migrate_local_state.py`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_migration.py`

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_control_api_migration.py` with:

```python
import json
import tempfile
import unittest
from pathlib import Path

from control_api.db import create_app_engine, init_db, session_scope
from control_api.migrate_local_state import migrate_local_state
from control_api.service import ControlService


class ControlApiMigrationTests(unittest.TestCase):
    def test_migration_imports_local_json_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "admins.json").write_text('["admin-a"]', encoding="utf-8")
            (root / "banned.json").write_text('["banned-a"]', encoding="utf-8")
            (root / "email_binds.json").write_text(
                '{"user-a":"a@example.com"}', encoding="utf-8"
            )
            (root / "cooldowns.json").write_text(
                json.dumps(
                    {
                        "restrict_rules": {
                            "163": {
                                "limit": 1,
                                "unit": "day",
                                "window": 86400,
                            }
                        },
                        "restrict_log": {"user-a": [1000]},
                    }
                ),
                encoding="utf-8",
            )

            engine = create_app_engine(f"sqlite:///{root}/control.db")
            init_db(engine)
            migrate_local_state(root, engine)
            service = ControlService(engine)

            self.assertEqual(service.get_email_binding("user-a"), "a@example.com")
            self.assertTrue(service.is_banned("banned-a"))
            self.assertEqual(service.get_resource_limit("163")["limit_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the migration test and confirm it fails**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_migration -v
```

Expected before implementation:

```text
ModuleNotFoundError for control_api
```

- [ ] **Step 3: Implement the migration script**

Read these local files if they exist:

```python
admins.json
banned.json
email_binds.json
staff.json
cooldowns.json
```

Import them into the database using `ControlService` methods.

- [ ] **Step 4: Run the migration test again**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_migration -v
```

Expected:

```text
OK
```

## Task 4: Bot Client And State Backend

**Files:**

- Create: `C:\Users\Administrator\Desktop\official_qqbot\control_api\client.py`
- Create: `C:\Users\Administrator\Desktop\official_qqbot\state_backend.py`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\bot.py`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_control_api_client.py`
- Test: `C:\Users\Administrator\Desktop\official_qqbot\tests\test_state_backend.py`

- [ ] **Step 1: Write the failing client and backend tests**

Create `tests/test_control_api_client.py` with:

```python
import json
import unittest

import httpx

from control_api.client import ControlApiClient


class ControlApiClientTests(unittest.TestCase):
    def test_check_limit_sends_bot_token_and_parses_response(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200,
                json={"blocked": True, "count": 1, "limit": 1, "window": 86400},
            )

        client = ControlApiClient(
            base_url="http://control",
            bot_token="bot-token",
            transport=httpx.MockTransport(handler),
        )

        result = client.check_resource_limit("163", "user-a")
        self.assertTrue(result["blocked"])
        self.assertEqual(calls[0].headers["x-bot-token"], "bot-token")


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_state_backend.py` with:

```python
import unittest

from state_backend import build_state_backend


class StateBackendTests(unittest.TestCase):
    def test_local_backend_is_default_without_control_api_url(self):
        backend = build_state_backend(control_api_base_url="", bot_token="")
        self.assertEqual(backend.backend_name, "local")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the client/backend tests and confirm they fail**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_client tests.test_state_backend -v
```

Expected before implementation:

```text
ModuleNotFoundError for control_api or state_backend
```

- [ ] **Step 3: Implement the client and backend selection**

Implement a sync HTTP client with methods for:

```python
get_user_state
set_email_binding
delete_email_binding
check_resource_limit
record_resource_usage
set_resource_limit
reset_resource_usage
log_command
log_outbound
```

Implement a backend factory that returns:

```python
LocalStateBackend
CloudStateBackend
```

Use local JSON and `shared_cooldown.py` when no control API URL is configured.

- [ ] **Step 4: Wire `bot.py` to the backend**

Route these behaviors through the backend object:

```python
_is_admin
_is_admin_or_staff
_is_banned
_get_bound_email
_require_bound_email
_check_resource_restrict
_record_resource_restrict
/auth
/admin
/ban
/unban
/addstaff
/deletestaff
/bind
/unbind
/restrict
/resetLimit
```

Keep the existing local path as the default fallback so the current tests stay green.

- [ ] **Step 5: Run the client/backend tests again**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_control_api_client tests.test_state_backend -v
```

Expected:

```text
OK
```

## Task 5: Dependencies And Deployment Docs

**Files:**

- Modify: `C:\Users\Administrator\Desktop\official_qqbot\requirements.txt`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\koishi-bridge.env.example`
- Modify: `C:\Users\Administrator\Desktop\official_qqbot\deploy\ubuntu\README.md`

- [ ] **Step 1: Update dependencies and env examples**

Add these dependencies:

```text
fastapi
sqlalchemy
uvicorn
psycopg[binary]
```

Add these env vars to the example:

```text
DATABASE_URL=sqlite:////opt/official_qqbot/data/control.db
CONTROL_API_BASE_URL=http://127.0.0.1:9000
BOT_CONTROL_TOKEN=replace-with-bot-token
ADMIN_CONTROL_TOKEN=replace-with-admin-token
```

- [ ] **Step 2: Update the deployment README**

Document:

```bash
python -m control_api.app
python -m control_api.migrate_local_state
```

and the production order:

```bash
1. Start the control API
2. Run the local JSON migration
3. Start the bot with CONTROL_API_BASE_URL configured
```

- [ ] **Step 3: Run the full verification suite**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m py_compile bot.py shared_cooldown.py handlers/sauth.py adapters/qq_official.py adapters/koishi_bridge.py adapters/nonebot_bridge.py control_api\*.py state_backend.py
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
node --check koishi-bridge/plugins/python-bridge/index.js
```

Expected:

```text
All tests pass.
Python syntax checks pass.
Node syntax check passes.
```

## Self-Review

- Spec coverage: This plan covers the Phase 2 cloud control API, database, migration script, bot-side state backend, and deploy docs.
- Placeholder scan: No `TODO`, `TBD`, or vague implementation steps remain.
- Type consistency: `ControlService` is the server-side DB wrapper, `ControlApiClient` is the bot-side HTTP client, and `build_state_backend()` chooses local or cloud behavior from `CONTROL_API_BASE_URL`.
