# Official QQ Private Message Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure each QQ private message executes at most once per bot process, including concurrent retries and delivery through both official and Koishi ingress.

**Architecture:** Replace the group-only ordered cache with one bounded inbound cache keyed by normalized message type, conversation identity, and message ID. Every normalized official or Koishi event registers synchronously before command processing can yield, while events without message IDs continue through unchanged.

**Tech Stack:** Python 3.10+, asyncio, `unittest`, `unittest.mock.AsyncMock`, existing QQ official and Koishi adapters

---

## File Structure

- Create `official_qqbot/tests/test_c2c_message_dedup.py`: focused private-message regression and compatibility tests.
- Modify `official_qqbot/bot.py:807-822`: rename and generalize the bounded inbound cache.
- Modify `official_qqbot/bot.py:1955-2006`: apply the shared check to official group, official C2C, and all Koishi message events before `process_message`.
- Modify `official_qqbot/tests/test_group_message_routing.py:7-9`: clear the renamed shared cache between group-routing tests.
- Modify `official_qqbot/tests/test_koishi_bridge_handler.py:7-9`: clear the renamed shared cache between bridge-handler tests.

### Task 1: Reproduce Private-Message Duplicate Delivery

**Files:**

- Create: `official_qqbot/tests/test_c2c_message_dedup.py`

- [ ] **Step 1: Add compatibility coverage for missing IDs and type namespaces**

Create the test file with the existing cache name so the characterization tests run before production code changes:

```python
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import bot


class C2CMessageDedupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot._recent_group_msg_ids.clear()

    async def test_c2c_messages_without_id_are_not_deduplicated(self):
        data = {
            "author": {"user_openid": "user-without-id"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(data)
            await bot.handle_c2c_message(data)

        self.assertEqual(process.await_count, 2)

    async def test_group_and_c2c_message_ids_use_separate_namespaces(self):
        group_data = {
            "group_openid": "shared-openid",
            "id": "shared-message-id",
            "author": {"member_openid": "group-user"},
            "content": "@bot /help",
        }
        c2c_data = {
            "id": "shared-message-id",
            "author": {"user_openid": "shared-openid"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_group_message(group_data)
            await bot.handle_c2c_message(c2c_data)

        self.assertEqual(process.await_count, 2)
```

- [ ] **Step 2: Run the compatibility tests**

Run from `official_qqbot`:

```powershell
python -m unittest discover -s tests -p "test_c2c_message_dedup.py" -v
```

Expected: 2 tests pass. They characterize behavior that the cache refactor must preserve.

- [ ] **Step 3: Add the sequential duplicate regression test**

Add this method to `C2CMessageDedupTests`:

```python
    async def test_duplicate_official_c2c_message_is_processed_once(self):
        data = {
            "id": "c2c-duplicate",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(data)
            await bot.handle_c2c_message(data)

        process.assert_awaited_once_with(
            {
                "type": "c2c",
                "group_openid": "",
                "user_openid": "private-user",
                "limit_user_id": "private-user",
                "msg_id": "c2c-duplicate",
            },
            "/help",
        )
```

- [ ] **Step 4: Run the sequential test and verify RED**

Run:

```powershell
python -m unittest discover -s tests -p "test_c2c_message_dedup.py" -v
```

Expected: `test_duplicate_official_c2c_message_is_processed_once` fails because `process_message` was awaited twice; the two compatibility tests still pass.

- [ ] **Step 5: Add the concurrent duplicate regression test**

Add this method to `C2CMessageDedupTests`:

```python
    async def test_concurrent_duplicate_c2c_message_is_processed_once(self):
        data = {
            "id": "c2c-concurrent",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_process(_ctx, _content):
            started.set()
            await release.wait()

        process = AsyncMock(side_effect=blocking_process)
        with patch.object(bot, "process_message", new=process):
            first = asyncio.create_task(bot.handle_c2c_message(data))
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(bot.handle_c2c_message(data))
            await asyncio.sleep(0)
            try:
                self.assertEqual(process.await_count, 1)
            finally:
                release.set()
                await asyncio.gather(first, second)
```

- [ ] **Step 6: Run the concurrent test and verify RED**

Run:

```powershell
python -m unittest discover -s tests -p "test_c2c_message_dedup.py" -v
```

Expected: both duplicate tests fail. The concurrent test reports an await count of 2, proving the second task entered command processing while the first was active.

- [ ] **Step 7: Add the cross-ingress duplicate regression test**

Add this method to `C2CMessageDedupTests`:

```python
    async def test_official_and_koishi_c2c_delivery_is_processed_once(self):
        official_data = {
            "id": "c2c-cross-ingress",
            "author": {"user_openid": "private-user"},
            "content": "/help",
        }
        koishi_payload = {
            "type": "c2c",
            "user_openid": "private-user",
            "msg_id": "c2c-cross-ingress",
            "content": "/help",
        }

        with patch.object(bot, "process_message", new_callable=AsyncMock) as process:
            await bot.handle_c2c_message(official_data)
            result = await bot.handle_koishi_bridge_payload(koishi_payload)

        self.assertEqual(
            result,
            {"ok": True, "ignored": True, "reason": "duplicate"},
        )
        process.assert_awaited_once()
```

End the file with:

```python

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8: Run all new tests and verify RED**

Run:

```powershell
python -m unittest discover -s tests -p "test_c2c_message_dedup.py" -v
```

Expected: 5 tests run; the three duplicate-delivery tests fail for duplicate execution, while the two compatibility tests pass.

### Task 2: Implement Unified Inbound Deduplication

**Files:**

- Modify: `official_qqbot/bot.py:807-822`
- Modify: `official_qqbot/bot.py:1955-2006`
- Modify: `official_qqbot/tests/test_c2c_message_dedup.py:9`
- Modify: `official_qqbot/tests/test_group_message_routing.py:9`
- Modify: `official_qqbot/tests/test_koishi_bridge_handler.py:9`

- [ ] **Step 1: Generalize the bounded cache**

Replace the group-only cache block in `bot.py` with:

```python
_INBOUND_MSG_CACHE_MAX = 1000
_recent_inbound_msg_ids: OrderedDict[tuple[str, str, str], float] = OrderedDict()


def _remember_inbound_message(
    message_type: str, conversation_id: str, msg_id: str
) -> bool:
    if not msg_id:
        return True

    key = (message_type, conversation_id, msg_id)
    if key in _recent_inbound_msg_ids:
        return False

    _recent_inbound_msg_ids[key] = _time_mod.time()
    while len(_recent_inbound_msg_ids) > _INBOUND_MSG_CACHE_MAX:
        _recent_inbound_msg_ids.popitem(last=False)
    return True
```

- [ ] **Step 2: Register official group and C2C events before processing**

Change the group guard to:

```python
    if not _remember_inbound_message(
        event.type, event.group_openid, event.msg_id
    ):
        _log.debug(
            f"[群消息去重] event={event.event_type} "
            f"group={event.group_openid} msg={event.msg_id}"
        )
        return
```

Insert this block in `handle_c2c_message` after the `if not event` return and before its info log or any `await`:

```python
    if not _remember_inbound_message(
        event.type, event.user_openid, event.msg_id
    ):
        _log.debug(
            f"[私聊去重] user={event.user_openid} msg={event.msg_id}"
        )
        return
```

- [ ] **Step 3: Register every normalized Koishi event before processing**

Replace the group-only Koishi guard with:

```python
    conversation_id = (
        event.group_openid if event.type == "group" else event.user_openid
    )
    if not _remember_inbound_message(
        event.type, conversation_id, event.msg_id
    ):
        _log.debug(
            f"[KoishiBridge去重] type={event.type} "
            f"conversation={conversation_id} msg={event.msg_id}"
        )
        return {"ok": True, "ignored": True, "reason": "duplicate"}
```

- [ ] **Step 4: Update test isolation for the renamed cache**

In all three test files, make `setUp` clear the unified cache:

```python
    def setUp(self):
        bot._recent_inbound_msg_ids.clear()
```

The files are:

```text
tests/test_c2c_message_dedup.py
tests/test_group_message_routing.py
tests/test_koishi_bridge_handler.py
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run from `official_qqbot`:

```powershell
python -m unittest discover -s tests -p "test_c2c_message_dedup.py" -v
python -m unittest discover -s tests -p "test_group_message_routing.py" -v
python -m unittest discover -s tests -p "test_koishi_bridge_handler.py" -v
```

Expected: 5 C2C tests, 5 group-routing tests, and 2 Koishi-handler tests pass. No test logs an unhandled task exception or timeout.

- [ ] **Step 6: Commit the tested implementation**

```powershell
git add -- official_qqbot/bot.py official_qqbot/tests/test_c2c_message_dedup.py official_qqbot/tests/test_group_message_routing.py official_qqbot/tests/test_koishi_bridge_handler.py
git commit -m "fix: deduplicate private message delivery"
```

### Task 3: Verify The Complete Bot Test Suite

**Files:**

- Verify: `official_qqbot/bot.py`
- Verify: `official_qqbot/tests/`

- [ ] **Step 1: Run the full Python test suite**

Run from `official_qqbot`:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all discovered tests pass. Any pre-existing environment-dependent failure must be identified separately; no failure may be ignored if it touches message adaptation, routing, bridge handling, webhook dispatch, or sending.

- [ ] **Step 2: Compile the changed Python files**

Run:

```powershell
python -m py_compile bot.py tests/test_c2c_message_dedup.py tests/test_group_message_routing.py tests/test_koishi_bridge_handler.py
```

Expected: exit code 0 with no output.

- [ ] **Step 3: Inspect the final diff**

Run from the repository root:

```powershell
git diff HEAD^ --check
git diff HEAD^ -- official_qqbot/bot.py official_qqbot/tests/test_c2c_message_dedup.py official_qqbot/tests/test_group_message_routing.py official_qqbot/tests/test_koishi_bridge_handler.py
```

Expected: no whitespace errors; only the bounded inbound cache, three ingress guards, and focused tests changed.

- [ ] **Step 4: Prepare production deployment commands**

After transferring the committed files to `154.44.31.213` without overwriting `/opt/official_qqbot/config.yaml` or runtime data, run:

```bash
cd /opt/official_qqbot
.venv/bin/python -m unittest discover -s tests -p 'test_c2c_message_dedup.py' -v
systemctl restart official-qqbot
systemctl is-active official-qqbot
journalctl -u official-qqbot -n 100 --no-pager
```

Expected: the regression tests pass, service state is `active`, and sending one private command produces one processing log and one response. Deployment requires shell access to the bot server and is not simulated by local tests.

## Self-Review

- Spec coverage: official C2C sequential and concurrent duplicates, cross-ingress C2C duplicates, missing IDs, type namespaces, existing group behavior, bounded cache, and deployment verification all map to explicit steps.
- Placeholder scan: no unresolved implementation steps or deferred decisions remain.
- Type consistency: the cache key is consistently `tuple[str, str, str]`; every caller supplies normalized `event.type`, one conversation ID, and `event.msg_id`.
- Scope check: no adapter, outbound sender, webhook acknowledgement, persistence, SAuth, or ACCC backend changes are included.
