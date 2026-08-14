# SAuth Client Timeout Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the Bot to wait for every ACCC SAuth request that completes within ACCC's 60-second group deadline.

**Architecture:** Keep the existing single-request, single-flight SAuth flow and change only its per-request HTTP timeout from 30 to 65 seconds. ACCC routing, retries, inventory handling, proxy selection, concurrency, and queue configuration remain unchanged.

**Tech Stack:** Python 3, `asyncio`, `httpx`, `unittest`, systemd

---

### Task 1: Prove And Implement The 65-Second Request Timeout

**Files:**
- Modify: `official_qqbot/tests/test_sauth_api.py:31`
- Modify: `official_qqbot/handlers/sauth.py:25`

- [ ] **Step 1: Change the focused test to require 65 seconds**

Rename the existing timeout assertion test and change only its expected request timeout:

```python
async def test_502_makes_exactly_one_post_with_sixty_five_second_timeout(self):
    client = Mock()
    client.post = AsyncMock(return_value=response(502))

    with patch.object(sauth, "_get_client", return_value=client), patch.object(
        sauth.asyncio, "sleep", new_callable=AsyncMock
    ):
        ok, message = await sauth.get_sauth()

    self.assertFalse(ok)
    self.assertIn("暂时不稳定", message)
    client.post.assert_awaited_once_with(
        sauth.SAUTH_API,
        headers={"X-Api-Key": sauth.SAUTH_API_KEY},
        timeout=65.0,
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run from `official_qqbot`:

```bash
python -m unittest tests.test_sauth_api.SauthApiTests.test_502_makes_exactly_one_post_with_sixty_five_second_timeout -v
```

Expected: FAIL because the actual call still contains `timeout=30.0`.

- [ ] **Step 3: Make the minimal production change**

Update the SAuth request constant without changing the shared client's defaults used by other endpoints:

```python
SAUTH_TIMEOUT_SECONDS = 65.0
```

- [ ] **Step 4: Run the focused test and verify GREEN**

```bash
python -m unittest tests.test_sauth_api.SauthApiTests.test_502_makes_exactly_one_post_with_sixty_five_second_timeout -v
```

Expected: PASS.

- [ ] **Step 5: Commit the tested behavior change**

```bash
git add official_qqbot/handlers/sauth.py official_qqbot/tests/test_sauth_api.py
git commit -m "fix: align bot sauth timeout with backend"
```

### Task 2: Verify The Bot Regression Surface

**Files:**
- Verify: `official_qqbot/handlers/sauth.py`
- Verify: `official_qqbot/tests/test_sauth_api.py`
- Verify: `official_qqbot/tests/test_source_secret_exposure.py`

- [ ] **Step 1: Run the complete SAuth test module**

Run from `official_qqbot`:

```bash
python -m unittest tests.test_sauth_api -v
```

Expected: all SAuth tests PASS, including single-flight, admission, cancellation, structured errors, and exactly-one-request assertions.

- [ ] **Step 2: Run the secret exposure test**

```bash
python -m unittest tests.test_source_secret_exposure -v
```

Expected: PASS with no API key or token committed to source.

- [ ] **Step 3: Run the full Python test suite**

```bash
python -m unittest discover -s tests -v
```

Expected: all Python tests PASS.

- [ ] **Step 4: Check the repository state**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors and no uncommitted implementation changes.

### Task 3: Deploy And Verify Production

**Files:**
- Deploy: `official_qqbot/handlers/sauth.py`
- Backup: `/opt/official_qqbot/handlers/sauth.py.pre-timeout-20260814`

- [ ] **Step 1: Verify the production service and secret injection**

On `38.58.59.215`, confirm `official-qqbot` is active and `SAUTH_API_KEY` is configured through `/etc/official-qqbot/koishi-bridge.env` without printing its value.

Expected: service active and `SAUTH_API_KEY_SET=true`.

- [ ] **Step 2: Back up and deploy the tested handler**

Copy the existing handler to `/opt/official_qqbot/handlers/sauth.py.pre-timeout-20260814`, then upload the committed `official_qqbot/handlers/sauth.py` to `/opt/official_qqbot/handlers/sauth.py`.

Expected: local and remote deployed handler SHA-256 values match.

- [ ] **Step 3: Restart and verify the Bot**

```bash
systemctl restart official-qqbot
curl -fsS http://127.0.0.1:8765/health
systemctl is-active official-qqbot
```

Expected: health succeeds and service state is `active`.

- [ ] **Step 4: Verify the running timeout and logs**

Confirm the deployed source contains `SAUTH_TIMEOUT_SECONDS = 65.0`, the main PID changed, and startup logs contain no traceback or authentication error.

- [ ] **Step 5: Push the implementation commits**

```bash
git push origin main
```

Expected: `origin/main` contains the design, plan, and implementation commits.

- [ ] **Step 6: Remove temporary diagnostic access**

After production verification, remove the `codex-diagnostic-20260814` public key from both `38.58.59.215` and `64.90.10.7`. Remove `/etc/ssh/sshd_config.d/00-codex-diagnostic.conf` from the backend and validate the remaining SSH configuration before reloading it.

Expected: the temporary public key is absent and both application services remain active.
