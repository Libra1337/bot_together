const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const ROOT_DIR = path.resolve(__dirname, "..");
const DEFAULT_CONFIG_PATH = path.join(ROOT_DIR, "data", "panel.json");

function joinForPlatform(...parts) {
  if (process.platform === "win32") {
    return path.join(...parts);
  }
  return path.posix.join(...parts.map((part) => String(part).replace(/\\/g, "/")));
}

function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString("hex");
  const digest = crypto
    .createHash("sha256")
    .update(`${salt}:${password}`)
    .digest("hex");
  return `sha256:${salt}:${digest}`;
}

function verifyPassword(password, passwordHash) {
  if (typeof password !== "string" || typeof passwordHash !== "string") {
    return false;
  }

  const [algorithm, salt, expected] = passwordHash.split(":");
  if (algorithm !== "sha256" || !salt || !expected) {
    return false;
  }

  const actual = crypto
    .createHash("sha256")
    .update(`${salt}:${password}`)
    .digest("hex");

  const actualBuffer = Buffer.from(actual);
  const expectedBuffer = Buffer.from(expected);
  if (actualBuffer.length !== expectedBuffer.length) {
    return false;
  }
  return crypto.timingSafeEqual(actualBuffer, expectedBuffer);
}

function defaultConfig() {
  const venvPython =
    process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
  const napcatBotsRoot =
    process.platform === "win32"
      ? "C:\\Users\\Administrator\\Desktop\\123"
      : "/opt/napcat_bots";
  const pythonCommand =
    process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
  const officialBot = {
    id: "official-bot",
    name: "Official Bot",
    kind: "python-bot",
    command: venvPython,
    entry: "bot.py",
    args: [],
    cwd: ".",
    env: {},
    stopTimeoutMs: 8000,
  };
  const napcatBase =
    process.platform === "win32"
      ? "C:\\Users\\Administrator\\Documents\\GitHub\\NapCatQQ"
      : "/opt/NapCatQQ";
  const napcatLauncher = (instanceName) =>
    process.platform === "win32"
      ? {
          command: "powershell.exe",
          entry: "",
          args: [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts\\start-napcat-instance.ps1",
            instanceName,
          ],
        }
      : {
          command: "bash",
          entry: "scripts/start-napcat-instance.sh",
          args: [instanceName],
        };
  const napcatQqbot = {
    id: "napcat-qqbot",
    name: "NapCat - qqbot 号",
    kind: "napcat",
    ...napcatLauncher("qqbot"),
    cwd: ".",
    env: {
      NAPCAT_ROOT: napcatBase,
      NAPCAT_INSTANCE: "qqbot",
    },
    webUrl: "http://127.0.0.1:6199/webui?token=panel-qqbot",
    disabled: false,
    stopTimeoutMs: 10000,
  };
  const napcatOnlyGroup = {
    id: "napcat-only-group",
    name: "NapCat - only群bot 号",
    kind: "napcat",
    ...napcatLauncher("only-group-bot"),
    cwd: ".",
    env: {
      NAPCAT_ROOT: napcatBase,
      NAPCAT_INSTANCE: "only-group-bot",
    },
    webUrl: "http://127.0.0.1:6200/webui?token=panel-only-group-bot",
    disabled: false,
    stopTimeoutMs: 10000,
  };
  return {
    server: {
      host: "0.0.0.0",
      port: 8787,
      publicUrl: "",
      sessionSecret: crypto.randomBytes(32).toString("hex"),
    },
    auth: {
      users: [
        {
          username: "admin",
          passwordHash: hashPassword("admin123456"),
          role: "admin",
        },
      ],
    },
    bot: {
      command: venvPython,
      entry: "bot.py",
      args: [],
      cwd: ".",
      env: {},
      stopTimeoutMs: 8000,
    },
    services: [
      officialBot,
      napcatQqbot,
      {
        id: "qqbot",
        name: "qqbot",
        kind: "python-bot",
        command: pythonCommand,
        entry: "bot.py",
        args: [],
        cwd:
          process.platform === "win32"
            ? path.join(napcatBotsRoot, "qqbot", "qqbot")
            : joinForPlatform(napcatBotsRoot, "qqbot"),
        env: {},
        dependsOn: ["napcat-qqbot"],
        requireHealthyBeforeStart: true,
        health: { type: "tcp", host: "127.0.0.1", port: 3001, timeoutMs: 500 },
        stopTimeoutMs: 8000,
      },
      napcatOnlyGroup,
      {
        id: "only-group-bot",
        name: "only群bot",
        kind: "python-bot",
        command: pythonCommand,
        entry: "bot.py",
        args: [],
        cwd:
          process.platform === "win32"
            ? path.join(napcatBotsRoot, "only群bot", "only群bot")
            : joinForPlatform(napcatBotsRoot, "only-group-bot"),
        env: {},
        dependsOn: ["napcat-only-group"],
        requireHealthyBeforeStart: true,
        health: { type: "tcp", host: "127.0.0.1", port: 3002, timeoutMs: 500 },
        stopTimeoutMs: 8000,
      },
    ],
    paths: {
      pluginsDir: "plugins",
      pluginState: "data/plugins.json",
      webDir: "web",
    },
  };
}

function mergeConfig(base, override) {
  const output = { ...base };
  for (const [key, value] of Object.entries(override || {})) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      base[key] &&
      typeof base[key] === "object" &&
      !Array.isArray(base[key])
    ) {
      output[key] = mergeConfig(base[key], value);
    } else {
      output[key] = value;
    }
  }
  return output;
}

function normalizeUsers(users) {
  return users.map((user) => {
    if (user.password && !user.passwordHash) {
      const { password, ...rest } = user;
      return { ...rest, passwordHash: hashPassword(password) };
    }
    return user;
  });
}

function botToOfficialService(bot = {}) {
  return {
    id: "official-bot",
    name: "Official Bot",
    kind: "python-bot",
    command: bot.command,
    entry: bot.entry,
    args: bot.args || [],
    cwd: bot.cwd,
    env: bot.env || {},
    stopTimeoutMs: bot.stopTimeoutMs || 8000,
  };
}

function isWindowsPathLike(value) {
  return /^[A-Za-z]:[\\/]/.test(String(value || ""));
}

function usesWindowsPython(command) {
  return /(?:^|[\\/])\.venv[\\/]Scripts[\\/]python\.exe$/i.test(String(command || ""));
}

function usesWindowsNapcatLauncher(service) {
  return (
    service.command === "powershell.exe" ||
    /start-napcat-instance\.ps1$/i.test(String(service.entry || "")) ||
    (Array.isArray(service.args) &&
      service.args.some((arg) => /start-napcat-instance\.ps1$/i.test(String(arg))))
  );
}

function needsNapcatLauncherMigration(service) {
  if (service.kind !== "napcat") {
    return false;
  }
  return usesWindowsNapcatLauncher(service);
}

function normalizeServiceForPlatform(service, defaultService) {
  if (process.platform === "win32") {
    if (needsNapcatLauncherMigration(service) && defaultService.kind === "napcat") {
      return {
        ...service,
        command: defaultService.command,
        entry: defaultService.entry,
        args: defaultService.args,
      };
    }
    return service;
  }

  if (defaultService.kind === "napcat" && usesWindowsNapcatLauncher(service)) {
    return {
      ...service,
      command: defaultService.command,
      entry: defaultService.entry,
      args: defaultService.args,
      env: {
        ...(service.env || {}),
        ...(defaultService.env || {}),
      },
    };
  }

  if (defaultService.kind === "python-bot") {
    const next = { ...service };
    if (usesWindowsPython(next.command)) {
      next.command = defaultService.command;
    }
    if (isWindowsPathLike(next.cwd)) {
      next.cwd = defaultService.cwd;
    }
    return next;
  }

  return service;
}

function normalizeServices(services, bot) {
  const defaults = defaultConfig().services;
  if (!Array.isArray(services) || services.length === 0) {
    return [botToOfficialService(bot), ...defaults.slice(1)];
  }

  const input = services.map((service) => ({ ...service }));
  const byId = new Map(input.map((service) => [service.id, service]));
  const oldNapcat = byId.get("napcat");
  const output = [];

  for (const defaultService of defaults) {
    let service = byId.get(defaultService.id);
    if (!service && defaultService.id === "official-bot") {
      service = botToOfficialService(bot);
    }
    if (!service && defaultService.kind === "napcat" && oldNapcat) {
      const instanceEnv = defaultService.env || {};
      service = {
        ...oldNapcat,
        id: defaultService.id,
        name: defaultService.name,
        env: {
          ...(oldNapcat.env || {}),
          ...instanceEnv,
        },
      };
    }
    if (!service) {
      service = defaultService;
    }

    if (defaultService.kind === "napcat") {
      const legacyUnconfigured =
        service.command === "node.exe" &&
        !service.entry &&
        Array.isArray(service.args) &&
        service.args.length === 0;
      if (service.disabled || legacyUnconfigured) {
        service = {
          ...defaultService,
          env: {
            ...(defaultService.env || {}),
            ...(service.env || {}),
          },
        };
      }
      service = normalizeServiceForPlatform(service, defaultService);
      service = {
        ...service,
        webUrl: defaultService.webUrl || service.webUrl,
      };
    } else {
      service = normalizeServiceForPlatform(service, defaultService);
    }

    if (service.id === "qqbot") {
      service = { ...service, dependsOn: ["napcat-qqbot"] };
    }
    if (service.id === "only-group-bot") {
      service = { ...service, dependsOn: ["napcat-only-group"] };
    }

    output.push(service);
  }

  const knownIds = new Set(defaults.map((service) => service.id));
  for (const service of input) {
    if (!knownIds.has(service.id) && service.id !== "napcat") {
      output.push(service);
    }
  }

  return output;
}

function loadConfig(configPath = process.env.PANEL_CONFIG || DEFAULT_CONFIG_PATH) {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });

  if (!fs.existsSync(configPath)) {
    const fresh = defaultConfig();
    fs.writeFileSync(configPath, `${JSON.stringify(fresh, null, 2)}\n`, "utf-8");
    return fresh;
  }

  const parsed = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  const merged = mergeConfig(defaultConfig(), parsed);
  merged.auth.users = normalizeUsers(merged.auth.users || []);
  merged.services = normalizeServices(parsed.services, merged.bot);
  fs.writeFileSync(configPath, `${JSON.stringify(merged, null, 2)}\n`, "utf-8");
  return merged;
}

module.exports = {
  DEFAULT_CONFIG_PATH,
  ROOT_DIR,
  defaultConfig,
  hashPassword,
  loadConfig,
  verifyPassword,
  normalizeServices,
};
