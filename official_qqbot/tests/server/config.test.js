const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { loadConfig, hashPassword, verifyPassword } = require("../../server/config");

function withTempDir(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "qqbot-config-"));
  try {
    return fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("loadConfig creates default panel config when missing", () => {
  withTempDir((dir) => {
    const configPath = path.join(dir, "panel.json");
    const config = loadConfig(configPath);

    assert.equal(config.server.host, "0.0.0.0");
    assert.equal(config.server.port, 8787);
    assert.equal(config.auth.users[0].username, "admin");
    assert.match(config.auth.users[0].passwordHash, /^sha256:/);
    assert.match(config.bot.command, /(?:^|[\\/])\.venv[\\/]Scripts[\\/]python\.exe$|(?:^|[\\/])\.venv[\\/]bin[\\/]python$/);
    assert.equal(config.bot.entry, "bot.py");
    assert.deepEqual(
      config.services.map((service) => service.id),
      ["official-bot", "napcat-qqbot", "qqbot", "napcat-only-group", "only-group-bot"]
    );
    const napcatQqbot = config.services.find((service) => service.id === "napcat-qqbot");
    const napcatOnlyGroup = config.services.find((service) => service.id === "napcat-only-group");
    assert.equal(napcatQqbot.disabled, false);
    if (process.platform === "win32") {
      assert.equal(napcatQqbot.command, "powershell.exe");
      assert.equal(napcatQqbot.entry, "");
      assert.deepEqual(napcatQqbot.args, [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts\\start-napcat-instance.ps1",
        "qqbot",
      ]);
      assert.equal(napcatQqbot.webUrl, "http://127.0.0.1:6199/webui?token=panel-qqbot");
    } else {
      assert.equal(napcatQqbot.command, "bash");
      assert.equal(napcatQqbot.entry, "scripts/start-napcat-instance.sh");
      assert.deepEqual(napcatQqbot.args, ["qqbot"]);
    }
    assert.equal(napcatOnlyGroup.disabled, false);
    if (process.platform === "win32") {
      assert.equal(napcatOnlyGroup.command, "powershell.exe");
      assert.equal(napcatOnlyGroup.entry, "");
      assert.deepEqual(napcatOnlyGroup.args, [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "scripts\\start-napcat-instance.ps1",
        "only-group-bot",
      ]);
      assert.equal(
        napcatOnlyGroup.webUrl,
        "http://127.0.0.1:6200/webui?token=panel-only-group-bot"
      );
    } else {
      assert.equal(napcatOnlyGroup.command, "bash");
      assert.equal(napcatOnlyGroup.entry, "scripts/start-napcat-instance.sh");
      assert.deepEqual(napcatOnlyGroup.args, ["only-group-bot"]);
    }
    assert.deepEqual(
      config.services.find((service) => service.id === "qqbot").dependsOn,
      ["napcat-qqbot"]
    );
    assert.deepEqual(
      config.services.find((service) => service.id === "only-group-bot").dependsOn,
      ["napcat-only-group"]
    );
    assert.equal(fs.existsSync(configPath), true);
  });
});

test("loadConfig migrates old single NapCat service into two NapCat instances", () => {
  withTempDir((dir) => {
    const configPath = path.join(dir, "panel.json");
    fs.writeFileSync(
      configPath,
      JSON.stringify({
        bot: { command: "python", entry: "bot.py", cwd: "custom-bot" },
        services: [
          { id: "official-bot", name: "Official Bot", command: "python", entry: "bot.py", cwd: "custom-bot" },
          { id: "napcat", name: "NapCat", kind: "napcat", command: "node", cwd: "/opt/NapCatQQ", disabled: true },
          { id: "qqbot", name: "qqbot", command: "python", entry: "bot.py", cwd: "/opt/qqbot", dependsOn: ["napcat"] },
          { id: "only-group-bot", name: "only群bot", command: "python", entry: "bot.py", cwd: "/opt/only", dependsOn: ["napcat"] },
        ],
      })
    );

    const config = loadConfig(configPath);
    const ids = config.services.map((service) => service.id);

    assert.ok(!ids.includes("napcat"));
    assert.ok(ids.includes("napcat-qqbot"));
    assert.ok(ids.includes("napcat-only-group"));
    assert.equal(config.services.find((service) => service.id === "napcat-qqbot").disabled, false);
    assert.equal(config.services.find((service) => service.id === "napcat-only-group").disabled, false);
    assert.deepEqual(
      config.services.find((service) => service.id === "qqbot").dependsOn,
      ["napcat-qqbot"]
    );
    assert.deepEqual(
      config.services.find((service) => service.id === "only-group-bot").dependsOn,
      ["napcat-only-group"]
    );
  });
});

test("loadConfig migrates old PowerShell NapCat launchers to bypass execution policy", () => {
  if (process.platform !== "win32") {
    return;
  }

  withTempDir((dir) => {
    const configPath = path.join(dir, "panel.json");
    fs.writeFileSync(
      configPath,
      JSON.stringify({
        services: [
          {
            id: "napcat-qqbot",
            name: "NapCat - qqbot 号",
            kind: "napcat",
            command: "powershell.exe",
            entry: "scripts\\start-napcat-instance.ps1",
            args: ["qqbot"],
            cwd: ".",
          },
          {
            id: "napcat-only-group",
            name: "NapCat - only群bot 号",
            kind: "napcat",
            command: "powershell.exe",
            entry: "scripts\\start-napcat-instance.ps1",
            args: ["only-group-bot"],
            cwd: ".",
          },
        ],
      })
    );

    const config = loadConfig(configPath);
    const napcatQqbot = config.services.find((service) => service.id === "napcat-qqbot");
    const napcatOnlyGroup = config.services.find((service) => service.id === "napcat-only-group");

    assert.equal(napcatQqbot.entry, "");
    assert.deepEqual(napcatQqbot.args, [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      "scripts\\start-napcat-instance.ps1",
      "qqbot",
    ]);
    assert.equal(napcatQqbot.webUrl, "http://127.0.0.1:6199/webui?token=panel-qqbot");
    assert.equal(napcatOnlyGroup.entry, "");
    assert.deepEqual(napcatOnlyGroup.args, [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      "scripts\\start-napcat-instance.ps1",
      "only-group-bot",
    ]);
    assert.equal(
      napcatOnlyGroup.webUrl,
      "http://127.0.0.1:6200/webui?token=panel-only-group-bot"
    );
  });
});

test("loadConfig migrates services to Linux defaults when a Windows panel config is deployed on Linux", () => {
  const originalPlatform = Object.getOwnPropertyDescriptor(process, "platform");
  Object.defineProperty(process, "platform", { value: "linux", configurable: true });
  withTempDir((dir) => {
    try {
      const configPath = path.join(dir, "panel.json");
      fs.writeFileSync(
        configPath,
        JSON.stringify({
          bot: { command: ".venv\\Scripts\\python.exe", entry: "bot.py", cwd: "." },
          services: [
            {
              id: "official-bot",
              name: "Official Bot",
              kind: "python-bot",
              command: ".venv\\Scripts\\python.exe",
              entry: "bot.py",
              cwd: ".",
            },
            {
              id: "napcat-qqbot",
              name: "NapCat - qqbot 号",
              kind: "napcat",
              command: "powershell.exe",
              entry: "",
              args: ["-File", "scripts\\start-napcat-instance.ps1", "qqbot"],
              cwd: ".",
              env: { NAPCAT_ROOT: "C:\\Users\\Administrator\\Documents\\GitHub\\NapCatQQ" },
            },
            {
              id: "qqbot",
              name: "qqbot",
              kind: "python-bot",
              command: ".venv\\Scripts\\python.exe",
              entry: "bot.py",
              cwd: "C:\\Users\\Administrator\\Desktop\\123\\qqbot\\qqbot",
            },
            {
              id: "napcat-only-group",
              name: "NapCat - only群bot 号",
              kind: "napcat",
              command: "powershell.exe",
              entry: "",
              args: ["-File", "scripts\\start-napcat-instance.ps1", "only-group-bot"],
              cwd: ".",
              env: { NAPCAT_ROOT: "C:\\Users\\Administrator\\Documents\\GitHub\\NapCatQQ" },
            },
            {
              id: "only-group-bot",
              name: "only群bot",
              kind: "python-bot",
              command: ".venv\\Scripts\\python.exe",
              entry: "bot.py",
              cwd: "C:\\Users\\Administrator\\Desktop\\123\\only群bot\\only群bot",
            },
          ],
        })
      );

      const config = loadConfig(configPath);
      const byId = new Map(config.services.map((service) => [service.id, service]));

      assert.equal(byId.get("official-bot").command, ".venv/bin/python");
      assert.equal(byId.get("napcat-qqbot").command, "bash");
      assert.equal(byId.get("napcat-qqbot").entry, "scripts/start-napcat-instance.sh");
      assert.equal(byId.get("napcat-qqbot").env.NAPCAT_ROOT, "/opt/NapCatQQ");
      assert.equal(byId.get("qqbot").command, ".venv/bin/python");
      assert.equal(byId.get("qqbot").cwd, "/opt/napcat_bots/qqbot");
      assert.equal(byId.get("napcat-only-group").command, "bash");
      assert.equal(byId.get("only-group-bot").cwd, "/opt/napcat_bots/only-group-bot");
    } finally {
      Object.defineProperty(process, "platform", originalPlatform);
    }
  });
});

test("legacy bot config is mirrored into official-bot service", () => {
  withTempDir((dir) => {
    const configPath = path.join(dir, "panel.json");
    fs.writeFileSync(
      configPath,
      JSON.stringify({
        bot: { command: "python", entry: "bot.py", cwd: "custom-bot" },
        services: [],
      })
    );

    const config = loadConfig(configPath);
    const official = config.services.find((service) => service.id === "official-bot");

    assert.equal(official.command, "python");
    assert.equal(official.entry, "bot.py");
    assert.equal(official.cwd, "custom-bot");
  });
});

test("verifyPassword accepts matching password and rejects wrong password", () => {
  const hash = hashPassword("secret-password");

  assert.equal(verifyPassword("secret-password", hash), true);
  assert.equal(verifyPassword("wrong", hash), false);
});
