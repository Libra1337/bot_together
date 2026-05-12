const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { spawnSync } = require("node:child_process");

const DEFAULT_INSTANCES = {
  qqbot: {
    onebotPort: 3001,
    webuiPort: 6199,
    botConfig: {
      win32: "C:\\Users\\Administrator\\Desktop\\123\\qqbot\\qqbot\\config.yaml",
      linux: "/opt/napcat_bots/qqbot/config.yaml",
    },
    botConfigEnv: "NAPCAT_QQBOT_CONFIG",
  },
  "only-group-bot": {
    onebotPort: 3002,
    webuiPort: 6200,
    botConfig: {
      win32: "C:\\Users\\Administrator\\Desktop\\123\\only群bot\\only群bot\\config.yaml",
      linux: "/opt/napcat_bots/only-group-bot/config.yaml",
    },
    botConfigEnv: "NAPCAT_ONLY_GROUP_BOT_CONFIG",
  },
};

function pickPlatformValue(value, platform) {
  if (!value || typeof value !== "object") {
    return value;
  }
  return value[platform] || value.default || value.linux || value.win32;
}

function getInstanceConfig(instanceName, options = {}) {
  const platform = options.platform || process.platform;
  const env = options.env || process.env;
  const instance = DEFAULT_INSTANCES[instanceName];
  if (!instance) {
    return null;
  }

  return {
    ...instance,
    botConfig:
      env[instance.botConfigEnv] ||
      pickPlatformValue(instance.botConfig, platform),
  };
}

function fail(message) {
  console.error(`[napcat-launcher] ${message}`);
  process.exit(1);
}

function readArg(name) {
  const prefix = `--${name}=`;
  const value = process.argv.find((arg) => arg.startsWith(prefix));
  return value ? value.slice(prefix.length) : "";
}

function findQQPath() {
  if (process.env.NAPCAT_QQ_PATH) return process.env.NAPCAT_QQ_PATH;
  if (process.platform !== "win32") {
    const candidates = [
      "/opt/QQ",
      "/opt/qq",
      "/usr/lib/qq",
      "/usr/lib64/qq",
      "/opt/QQ/resources/app",
      "/usr/share/tencent-qq",
    ];
    const found = candidates.find((candidate) => fs.existsSync(candidate));
    if (found) {
      return found;
    }
    fail("Linux 上请设置 NAPCAT_QQ_PATH 指向 QQ 可执行文件或 QQ 安装目录，例如 /opt/QQ/qq。");
  }

  const command = [
    "$paths=@(",
    "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\QQ',",
    "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\QQ',",
    "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\QQ',",
    "'HKCU:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\QQ'",
    ");",
    "foreach($regPath in $paths){",
    "$item=Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue;",
    "if(-not $item){continue}",
    "if($item.InstallLocation -and (Test-Path $item.InstallLocation)){Write-Output $item.InstallLocation; exit 0}",
    "if($item.UninstallString){",
    "$uninstall=$item.UninstallString.Trim('\"');",
    "$dir=Split-Path $uninstall -Parent;",
    "if($dir -and (Test-Path $dir)){Write-Output $dir; exit 0}",
    "$root=[System.IO.Path]::GetPathRoot($uninstall);",
    "if($root -and (Test-Path (Join-Path $root 'versions'))){Write-Output $root; exit 0}",
    "}",
    "}",
    "$candidates=@(",
    "'E:\\',",
    "'D:\\',",
    "'C:\\Program Files\\Tencent\\QQNT',",
    "'C:\\Program Files (x86)\\Tencent\\QQNT',",
    "'C:\\Program Files\\Tencent\\QQ',",
    "'C:\\Program Files (x86)\\Tencent\\QQ'",
    ");",
    "foreach($candidate in $candidates){if(Test-Path $candidate){Write-Output $candidate; exit 0}}",
    "exit 1",
  ].join(" ");
  const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf-8",
  });
  if (result.status !== 0) {
    fail(`未找到 QQ 安装路径，请设置 NAPCAT_QQ_PATH。${result.stderr || ""}`);
  }
  const qqPath = result.stdout.trim();
  if (!qqPath || !fs.existsSync(qqPath)) {
    fail(`QQ 安装路径不存在: ${qqPath || "(empty)"}`);
  }
  return qqPath;
}

function latestQQAppDir(qqPath) {
  if (process.platform !== "win32") {
    const stat = fs.existsSync(qqPath) ? fs.statSync(qqPath) : null;
    const baseDir = stat?.isFile() ? path.dirname(qqPath) : qqPath;
    const appDir = path.join(baseDir, "resources", "app");
    if (!fs.existsSync(appDir)) {
      fail(`QQ resources/app 目录不存在: ${appDir}`);
    }
    return {
      versionsDir: path.join(baseDir, "resources", "app", "versions"),
      appDir,
      qqMainPath: stat?.isFile() ? qqPath : path.join(baseDir, "qq"),
    };
  }

  const versionsDir = path.join(qqPath, "versions");
  if (!fs.existsSync(versionsDir)) {
    fail(`QQ versions 目录不存在: ${versionsDir}`);
  }
  const versions = fs
    .readdirSync(versionsDir)
    .map((name) => ({ name, fullPath: path.join(versionsDir, name) }))
    .filter((item) => fs.statSync(item.fullPath).isDirectory())
    .sort((a, b) => fs.statSync(b.fullPath).mtimeMs - fs.statSync(a.fullPath).mtimeMs);
  if (versions.length === 0) {
    fail(`QQ versions 目录下没有版本目录: ${versionsDir}`);
  }
  return {
    versionsDir,
    appDir: path.join(versions[0].fullPath, "resources", "app"),
    qqMainPath: qqPath,
  };
}

function copyIfNeeded(source, target) {
  if (fs.existsSync(target)) return;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}

function copyDirIfNeeded(sourceDir, targetDir, names) {
  fs.mkdirSync(targetDir, { recursive: true });
  for (const name of names) {
    copyIfNeeded(path.join(sourceDir, name), path.join(targetDir, name));
  }
}

function readOnebotToken(configPath) {
  const text = fs.readFileSync(configPath, "utf-8");
  const match = text.match(/^\s*token:\s*["']?([^"'\r\n#]+)["']?/m);
  if (!match) {
    fail(`无法从 bot 配置读取 OneBot token: ${configPath}`);
  }
  return match[1].trim();
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf-8");
}

function ensureRuntimeFiles({ qqPath, appDir, workDir, napcatRoot }) {
  if (process.platform !== "win32") {
    return appDir;
  }

  const targetRuntime = path.join(workDir, "runtime");
  const targetWin64 = path.join(targetRuntime, "win64");
  const qqntDll = path.join(napcatRoot, "packages", "napcat-develop", "QQNT.dll");

  copyIfNeeded(qqntDll, path.join(targetRuntime, "QQNT.dll"));
  copyIfNeeded(path.join(qqPath, "versions", "config.json"), path.join(targetRuntime, "config.json"));
  copyDirIfNeeded(appDir, targetRuntime, [
    "avif_convert.dll",
    "broadcast_ipc.dll",
    "libglib-2.0-0.dll",
    "libgobject-2.0-0.dll",
    "libvips-42.dll",
    "ncnn.dll",
    "opencv.dll",
    "package.json",
    "QBar.dll",
    "wrapper.node",
    "LightQuic.dll",
  ]);
  copyDirIfNeeded(path.join(appDir, "win64"), targetWin64, [
    "SSOShareInfoHelper64.dll",
    "parent-ipc-core-x64.dll",
  ]);

  return targetRuntime;
}

function resolveNapcatRoot() {
  if (process.env.NAPCAT_ROOT) {
    return process.env.NAPCAT_ROOT;
  }
  return process.platform === "win32"
    ? "C:\\Users\\Administrator\\Documents\\GitHub\\NapCatQQ"
    : "/opt/NapCatQQ";
}

function assertReadableFile(filePath, message) {
  if (!fs.existsSync(filePath)) {
    fail(`${message}: ${filePath}`);
  }
}

function napcatWorkspacePath(napcatRoot) {
  return path.join(napcatRoot, "pnpm-workspace.yaml");
}

function ensureNapcatWorkspaceConfig(napcatRoot) {
  const workspacePath = napcatWorkspacePath(napcatRoot);
  const desiredSuffix = "dangerouslyAllowAllBuilds: true\n";
  const desiredHeader = "packages:\n  - packages/*\n";

  if (!fs.existsSync(workspacePath)) {
    fs.writeFileSync(workspacePath, `${desiredHeader}${desiredSuffix}`, "utf-8");
    return;
  }

  const current = fs.readFileSync(workspacePath, "utf-8");
  if (/^\s*dangerouslyAllowAllBuilds\s*:\s*true\s*$/m.test(current)) {
    return;
  }

  const next = current.endsWith("\n") ? current : `${current}\n`;
  fs.writeFileSync(workspacePath, `${next}${desiredSuffix}`, "utf-8");
}

function napcatShellDir(napcatRoot) {
  return path.join(napcatRoot, "packages", "napcat-shell");
}

function napcatShellDistPath(napcatRoot) {
  return path.join(napcatShellDir(napcatRoot), "dist", "napcat.mjs");
}

function hasNapcatShellDependency(napcatRoot, packageName) {
  const shellDir = napcatShellDir(napcatRoot);
  return [
    path.join(shellDir, "node_modules", packageName),
    path.join(napcatRoot, "node_modules", packageName),
  ].some((candidate) => fs.existsSync(candidate));
}

function runNapcatPackageManager(napcatRoot, args) {
  const normalizedArgs =
    args[0] === "install"
      ? [...args, "--dangerously-allow-all-builds"]
      : args;
  const commands = [
    ["corepack", ["pnpm", ...normalizedArgs]],
    ["pnpm", normalizedArgs],
    ["npm", ["exec", "--yes", "pnpm", "--", ...normalizedArgs]],
  ];

  let lastError = "";
  for (const [command, commandArgs] of commands) {
    const result = spawnSync(command, commandArgs, {
      cwd: napcatRoot,
      encoding: "utf-8",
      stdio: "pipe",
      env: {
        ...process.env,
        PATH: process.env.PATH,
      },
    });
    if (result.stdout) {
      process.stdout.write(result.stdout);
    }
    if (result.stderr) {
      process.stderr.write(result.stderr);
    }
    if (result.status === 0) {
      return;
    }
    lastError = result.stderr || result.stdout || `${command} ${commandArgs.join(" ")}`;
  }

  fail(`NapCat 依赖安装失败，请在 ${napcatRoot} 下手动执行 pnpm install / pnpm build:shell。${lastError ? `\n${lastError}` : ""}`);
}

function ensureNapcatShellReady(napcatRoot) {
  const shellDir = napcatShellDir(napcatRoot);
  const distPath = napcatShellDistPath(napcatRoot);
  if (!fs.existsSync(shellDir)) {
    fail(`NapCat 目录不存在: ${shellDir}`);
  }
  ensureNapcatWorkspaceConfig(napcatRoot);

  if (!hasNapcatShellDependency(napcatRoot, "express")) {
    console.log("[napcat-launcher] napcat-shell 依赖缺失，正在执行 pnpm install");
    runNapcatPackageManager(napcatRoot, ["install"]);
  }

  if (!fs.existsSync(distPath)) {
    console.log("[napcat-launcher] napcat-shell 未构建，正在执行 pnpm build:shell");
    runNapcatPackageManager(napcatRoot, ["build:shell"]);
  }
}

function isMissingPackageImportError(error) {
  return Boolean(
    error &&
      error.code === "ERR_MODULE_NOT_FOUND" &&
      /Cannot find package ['"][^'"]+['"] imported from /.test(String(error.message || ""))
  );
}

async function main() {
  const instanceName = readArg("instance") || process.argv[2];
  const instance = getInstanceConfig(instanceName);
  if (!instance) {
    fail(`未知实例: ${instanceName || "(empty)"}`);
  }

  const napcatRoot = resolveNapcatRoot();
  const napcatMjs = napcatShellDistPath(napcatRoot);
  if (!fs.existsSync(napcatMjs)) {
    fail(`NapCat 尚未 build: ${napcatMjs}。请先在 NapCatQQ 目录运行 pnpm install，然后运行 pnpm build:shell。`);
  }

  ensureNapcatShellReady(napcatRoot);

  const qqPath = findQQPath();
  const { appDir, qqMainPath } = latestQQAppDir(qqPath);
  if (!fs.existsSync(appDir)) {
    fail(`QQ app 目录不存在: ${appDir}`);
  }

  const workDir = path.resolve(
    process.env.NAPCAT_PANEL_WORKDIR || path.join(__dirname, "..", "data", "napcat", instanceName)
  );
  const runtimeDir = ensureRuntimeFiles({ qqPath, appDir, workDir, napcatRoot });
  assertReadableFile(instance.botConfig, "Bot 配置不存在，请先部署对应 NapCat bot 配置");
  const token = readOnebotToken(instance.botConfig);

  writeJson(path.join(workDir, "config", "webui.json"), {
    host: "127.0.0.1",
    port: instance.webuiPort,
    prefix: "",
    token: `panel-${instanceName}`,
    loginRate: 3,
    accessControlMode: "none",
    ipWhitelist: [],
    ipBlacklist: [],
    enableXForwardedFor: false,
  });

  writeJson(path.join(workDir, "config", "onebot11.json"), {
    network: {
      httpServers: [],
      httpSseServers: [],
      httpClients: [],
      websocketServers: [
        {
          enable: true,
          name: `WebSocket-${instanceName}`,
          host: "127.0.0.1",
          port: instance.onebotPort,
          reportSelfMessage: false,
          enableForcePushEvent: true,
          messagePostFormat: "array",
          token,
          debug: false,
          heartInterval: 30000,
        },
      ],
      websocketClients: [],
      plugins: [],
    },
    musicSignUrl: "",
    enableLocalFile2Url: false,
    parseMultMsg: false,
    imageDownloadProxy: "",
  });

  process.env.NAPCAT_WRAPPER_PATH = path.join(runtimeDir, "wrapper.node");
  process.env.NAPCAT_QQ_PACKAGE_INFO_PATH = path.join(runtimeDir, "package.json");
  const versionConfigPath =
    process.platform === "win32"
      ? path.join(runtimeDir, "config.json")
      : path.join(path.dirname(qqMainPath), "resources", "app", "versions", "config.json");
  if (fs.existsSync(versionConfigPath)) {
    process.env.NAPCAT_QQ_VERSION_CONFIG_PATH = versionConfigPath;
  }
  process.env.NAPCAT_DISABLE_PIPE = "1";
  process.env.NAPCAT_DISABLE_MULTI_PROCESS = "1";
  process.env.NAPCAT_WORKDIR = workDir;
  process.env.NAPCAT_WEBUI_JWT_SECRET_KEY = `panel-${instanceName}-jwt`;
  process.env.NAPCAT_WEBUI_SECRET_KEY = `panel-${instanceName}`;
  process.env.NAPCAT_WEBUI_PREFERRED_PORT = String(instance.webuiPort);

  console.log(`[napcat-launcher] instance=${instanceName}`);
  console.log(`[napcat-launcher] workdir=${workDir}`);
  console.log(`[napcat-launcher] botConfig=${instance.botConfig}`);
  console.log(`[napcat-launcher] onebot=127.0.0.1:${instance.onebotPort}`);
  console.log(`[napcat-launcher] webui=http://127.0.0.1:${instance.webuiPort}/webui/`);
  if (process.platform !== "win32") {
    Object.defineProperty(process, "execPath", {
      value: qqMainPath,
      configurable: true,
    });
  }
  const napcatModuleUrl = pathToFileURL(napcatMjs).href;
  try {
    await import(napcatModuleUrl);
  } catch (error) {
    if (isMissingPackageImportError(error)) {
      console.log("[napcat-launcher] NapCat 模块缺依赖，正在重新执行 pnpm install");
      runNapcatPackageManager(napcatRoot, ["install"]);
      await import(`${napcatModuleUrl}?retry=1`);
      return;
    }
    throw error;
  }
}

if (process.env.NAPCAT_LAUNCHER_TEST !== "1") {
  main().catch((error) => {
    fail(error.stack || error.message);
  });
}

module.exports = {
  DEFAULT_INSTANCES,
  ensureNapcatShellReady,
  ensureNapcatWorkspaceConfig,
  getInstanceConfig,
  hasNapcatShellDependency,
  pickPlatformValue,
  napcatShellDistPath,
  napcatShellDir,
  napcatWorkspacePath,
  runNapcatPackageManager,
};
