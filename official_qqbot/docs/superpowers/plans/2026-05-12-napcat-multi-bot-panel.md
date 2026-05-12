# NapCat Multi-Bot Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Node.js panel into a multi-service supervisor for the official bot, two NapCat instances, `qqbot`, and `only群bot`.

**Architecture:** Replace the single hard-coded bot process manager with a generic service supervisor that loads service definitions from `data/panel.json`. The HTTP API exposes service start/stop/status/log operations, keeps legacy bot endpoints for compatibility, and the static frontend renders one control card per service.

**Tech Stack:** Node.js CommonJS server, built-in `node:test`, static HTML/CSS/JS frontend, Python bot processes, TCP socket health checks.

---

## File Structure

- Modify `server/config.js`: add default `services`, path normalization, and public config redaction.
- Create `server/serviceManager.js`: generic `ManagedService` and `ServiceRegistry` with per-service logs, start/stop, health checks, and SSE log fanout.
- Modify `server/app.js`: replace single `BotProcessManager` usage with `ServiceRegistry`, add `/api/services/:id/*` endpoints, preserve `/api/bot/start` and `/api/bot/stop`.
- Modify `web/app.js`: render service cards, call new service endpoints, filter logs by service.
- Modify `web/index.html`: add service dashboard containers.
- Modify `web/styles.css`: style service cards and log filters.
- Add `tests/server/serviceManager.test.js`: service manager unit tests.
- Modify `tests/server/app.test.js` if present, or add `tests/server/app.test.js`: API tests for multi-service status and legacy bot compatibility.
- Modify `docs/linux-deploy.md`: explain NapCat services, local OneBot ports, and systemd panel deployment.

## Task 1: Service Manager

**Files:**
- Create: `server/serviceManager.js`
- Test: `tests/server/serviceManager.test.js`

- [ ] **Step 1: Write failing service manager tests**

Create `tests/server/serviceManager.test.js` with tests for:

```js
const assert = require("node:assert/strict");
const net = require("node:net");
const test = require("node:test");
const { ManagedService, ServiceRegistry, probeTcp } = require("../../server/serviceManager");

function makeNodeService(id, code) {
  return {
    id,
    name: id,
    command: process.execPath,
    entry: "-e",
    args: [code],
    cwd: process.cwd(),
    env: {},
    stopTimeoutMs: 1000,
  };
}

test("probeTcp returns false for closed local port", async () => {
  const ok = await probeTcp("127.0.0.1", 9, 100);
  assert.equal(ok, false);
});

test("probeTcp returns true for open local port", async () => {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    const ok = await probeTcp("127.0.0.1", port, 500);
    assert.equal(ok, true);
  } finally {
    server.close();
  }
});

test("ManagedService starts, captures logs, and stops", async () => {
  const service = new ManagedService(
    makeNodeService("demo", "console.log('ready'); setInterval(() => {}, 1000);")
  );

  const status = await service.start();
  assert.equal(status.running, true);
  assert.equal(status.id, "demo");

  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.match(service.getLogs(20).map((entry) => entry.line).join("\n"), /ready/);

  const stopped = await service.stop();
  assert.equal(stopped.running, false);
});

test("ServiceRegistry starts service by id and streams service-tagged logs", async () => {
  const registry = new ServiceRegistry([
    makeNodeService("alpha", "console.log('alpha-log'); setInterval(() => {}, 1000);"),
  ]);

  const seen = [];
  registry.on("log", (entry) => seen.push(entry));
  await registry.start("alpha");
  await new Promise((resolve) => setTimeout(resolve, 100));

  assert.equal(registry.getStatus().services[0].id, "alpha");
  assert.equal(registry.getStatus().services[0].running, true);
  assert.ok(seen.some((entry) => entry.serviceId === "alpha"));

  await registry.stop("alpha");
});
```

- [ ] **Step 2: Run service manager tests and verify they fail**

Run: `node --test tests/server/serviceManager.test.js`

Expected: FAIL because `server/serviceManager.js` does not exist.

- [ ] **Step 3: Implement `server/serviceManager.js`**

Implement exports:

```js
module.exports = { ManagedService, ServiceRegistry, probeTcp };
```

The implementation must:

- Spawn configured commands with `windowsHide: true`.
- Apply UTF-8 Python env variables by default.
- Add `serviceId`, `serviceName`, `ts`, `stream`, and `line` to each log entry.
- Support `getStatus()`, `getLogs(limit)`, `start()`, `stop()`.
- Support TCP health config: `{ type: "tcp", host: "127.0.0.1", port: 3001, timeoutMs: 500 }`.
- Have `ServiceRegistry` methods: `get(id)`, `getStatus()`, `getLogs(limit, serviceId)`, `start(id)`, `stop(id)`, `checkHealth()`.

- [ ] **Step 4: Run tests and verify they pass**

Run: `node --test tests/server/serviceManager.test.js`

Expected: PASS.

## Task 2: Config Migration

**Files:**
- Modify: `server/config.js`
- Test: `tests/server/config.test.js`

- [ ] **Step 1: Inspect existing config tests**

Run: `Get-ChildItem tests/server`

Expected: See current server test files and avoid replacing unrelated tests.

- [ ] **Step 2: Add or update config tests**

Add tests that:

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { loadConfig } = require("../../server/config");

test("loadConfig creates default services including official bot and NapCat bots", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "panel-config-"));
  const cfg = loadConfig(path.join(dir, "panel.json"));
  const ids = cfg.services.map((service) => service.id);
  assert.ok(ids.includes("official-bot"));
  assert.ok(ids.includes("napcat"));
  assert.ok(ids.includes("qqbot"));
  assert.ok(ids.includes("only-group-bot"));
});

test("legacy bot config is mirrored into official-bot service", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "panel-config-"));
  const cfgPath = path.join(dir, "panel.json");
  fs.writeFileSync(
    cfgPath,
    JSON.stringify({
      bot: { command: "python", entry: "bot.py", cwd: "custom-bot" },
      services: [],
    })
  );
  const cfg = loadConfig(cfgPath);
  const official = cfg.services.find((service) => service.id === "official-bot");
  assert.equal(official.command, "python");
  assert.equal(official.entry, "bot.py");
  assert.equal(official.cwd, "custom-bot");
});
```

- [ ] **Step 3: Run config tests and verify they fail**

Run: `node --test tests/server/config.test.js`

Expected: FAIL until services defaults are implemented.

- [ ] **Step 4: Implement config services**

Update `server/config.js` so `defaultConfig()` includes a `services` array with:

- `official-bot`: current bot command/entry/cwd.
- `napcat-qqbot`: placeholder command suitable for later user editing, default disabled.
- `napcat-only-group`: placeholder command suitable for later user editing, default disabled.
- `qqbot`: Python command pointing at `C:\Users\Administrator\Desktop\123\qqbot\qqbot` on Windows and `/opt/napcat_bots/qqbot` on Linux, depending on `napcat-qqbot`.
- `only-group-bot`: Python command pointing at `C:\Users\Administrator\Desktop\123\only群bot\only群bot` on Windows and `/opt/napcat_bots/only-group-bot` on Linux, depending on `napcat-only-group`.

Keep `bot` for compatibility, and if `services` is missing or empty, mirror `bot` into `official-bot`.

- [ ] **Step 5: Run config tests**

Run: `node --test tests/server/config.test.js`

Expected: PASS.

## Task 3: API Integration

**Files:**
- Modify: `server/app.js`
- Test: `tests/server/app.test.js`

- [ ] **Step 1: Add API tests**

Create or update `tests/server/app.test.js` to verify:

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { createApp } = require("../../server/app");
const { hashPassword } = require("../../server/config");

function writeConfig() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "panel-app-"));
  const webDir = path.join(dir, "web");
  fs.mkdirSync(webDir);
  fs.writeFileSync(path.join(webDir, "index.html"), "ok");
  const configPath = path.join(dir, "panel.json");
  fs.writeFileSync(
    configPath,
    JSON.stringify({
      server: { host: "127.0.0.1", port: 0, publicUrl: "", sessionSecret: "test" },
      auth: {
        users: [
          { username: "admin", passwordHash: hashPassword("pw"), role: "admin" },
        ],
      },
      paths: { pluginsDir: path.join(dir, "plugins"), pluginState: path.join(dir, "plugins.json"), webDir },
      bot: { command: process.execPath, entry: "-e", args: ["setInterval(()=>{},1000)"], cwd: dir },
      services: [
        { id: "official-bot", name: "Official Bot", command: process.execPath, entry: "-e", args: ["setInterval(()=>{},1000)"], cwd: dir },
      ],
    })
  );
  return configPath;
}

async function request(base, path, options = {}) {
  const res = await fetch(`${base}${path}`, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

test("service status and legacy bot endpoints work after login", async () => {
  const { server } = createApp({ configPath: writeConfig() });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const login = await request(base, "/api/login", {
      method: "POST",
      body: JSON.stringify({ username: "admin", password: "pw" }),
    });
    assert.equal(login.res.status, 200);
    const cookie = login.res.headers.get("set-cookie");

    const status = await request(base, "/api/status", { headers: { cookie } });
    assert.equal(status.res.status, 200);
    assert.ok(Array.isArray(status.data.services));
    assert.equal(status.data.bot.id, "official-bot");

    const start = await request(base, "/api/bot/start", { method: "POST", headers: { cookie } });
    assert.equal(start.res.status, 200);
    assert.equal(start.data.bot.running, true);

    const stop = await request(base, "/api/services/official-bot/stop", { method: "POST", headers: { cookie } });
    assert.equal(stop.res.status, 200);
    assert.equal(stop.data.service.running, false);
  } finally {
    server.close();
  }
});
```

- [ ] **Step 2: Run API test and verify it fails**

Run: `node --test tests/server/app.test.js`

Expected: FAIL until `server/app.js` exposes `services`.

- [ ] **Step 3: Update `server/app.js`**

Replace `BotProcessManager` usage with `ServiceRegistry`.

Expose:

- `GET /api/status`: `{ bot, services, plugins, config }`, where `bot` is `official-bot`.
- `POST /api/services/:id/start`: `{ service }`.
- `POST /api/services/:id/stop`: `{ service }`.
- `GET /api/services/:id/logs`: `{ logs }`.
- `GET /api/logs`: supports optional `?serviceId=...`.
- `GET /api/logs/stream`: emits all service logs.
- Legacy `POST /api/bot/start` and `/api/bot/stop` map to `official-bot`.

- [ ] **Step 4: Run API tests**

Run: `node --test tests/server/app.test.js`

Expected: PASS.

## Task 4: Frontend Multi-Service Dashboard

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/styles.css`

- [ ] **Step 1: Update HTML containers**

Add:

- `#serviceList` for cards.
- `#logServiceFilter` select.
- Keep old element IDs only if `web/app.js` still references them.

- [ ] **Step 2: Update frontend JS**

In `web/app.js`:

- Store `state.services`.
- Render service cards from `data.services`.
- Start button calls `POST /api/services/:id/start`.
- Stop button calls `POST /api/services/:id/stop`.
- Log filter calls `/api/logs?limit=300&serviceId=<id>`.
- `formatLog()` includes service name.

- [ ] **Step 3: Update CSS**

Add responsive grid styling for service cards and compact status badges. Keep cards no more than 8px radius.

- [ ] **Step 4: Manual browser check**

Run: `npm start`

Open: `http://127.0.0.1:8787/`

Expected: login screen works, dashboard shows service cards, buttons do not overlap, logs render.

## Task 5: Deployment Notes

**Files:**
- Modify: `docs/linux-deploy.md`

- [ ] **Step 1: Add NapCat multi-service section**

Document:

- Keep public TCP `8787` open.
- Keep OneBot ports `3001` and `3002` bound to `127.0.0.1`.
- Use panel config `data/panel.json` to adjust NapCat command and bot paths.
- Create Python venvs for both bot folders.
- systemd only needs to keep panel alive.

- [ ] **Step 2: Verify docs do not include secrets**

Run: `Select-String -Path docs/linux-deploy.md -Pattern "sk-|token:|api_key|smtp_pass"`

Expected: no output.

## Task 6: Full Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run all server tests**

Run: `npm test`

Expected: all tests pass.

- [ ] **Step 2: Start panel locally**

Run: `npm start`

Expected: `[panel] listening on http://0.0.0.0:8787`.

- [ ] **Step 3: Inspect `data/panel.json`**

Confirm services exist and secret fields are not exposed through `/api/status`.
