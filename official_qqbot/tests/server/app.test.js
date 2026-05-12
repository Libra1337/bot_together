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
      paths: {
        pluginsDir: path.join(dir, "plugins"),
        pluginState: path.join(dir, "plugins.json"),
        webDir,
      },
      bot: {
        command: process.execPath,
        entry: "-e",
        args: ["setInterval(()=>{},1000)"],
        cwd: dir,
      },
      services: [
        {
          id: "official-bot",
          name: "Official Bot",
          command: process.execPath,
          entry: "-e",
          args: ["setInterval(()=>{},1000)"],
          cwd: dir,
        },
      ],
    })
  );
  return configPath;
}

async function request(base, requestPath, options = {}) {
  const res = await fetch(`${base}${requestPath}`, {
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

    const start = await request(base, "/api/bot/start", {
      method: "POST",
      headers: { cookie },
    });
    assert.equal(start.res.status, 200);
    assert.equal(start.data.bot.running, true);

    const stop = await request(base, "/api/services/official-bot/stop", {
      method: "POST",
      headers: { cookie },
    });
    assert.equal(stop.res.status, 200);
    assert.equal(stop.data.service.running, false);
  } finally {
    server.close();
  }
});
