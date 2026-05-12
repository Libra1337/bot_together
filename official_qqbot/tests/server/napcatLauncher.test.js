const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const ROOT_DIR = path.resolve(__dirname, "..", "..");

test("Linux NapCat startup script is present and dispatches to the launcher", () => {
  const scriptPath = path.join(ROOT_DIR, "scripts", "start-napcat-instance.sh");

  assert.equal(fs.existsSync(scriptPath), true);
  const script = fs.readFileSync(scriptPath, "utf-8");
  assert.match(script, /napcat-launcher\.cjs/);
  assert.match(script, /--instance=\$INSTANCE/);
});

test("Linux NapCat startup script preloads QQ magic shim and gnutls", () => {
  const scriptPath = path.join(ROOT_DIR, "scripts", "start-napcat-instance.sh");
  const shimPath = path.join(ROOT_DIR, "scripts", "napcat-qqmagic-shim.c");

  assert.equal(fs.existsSync(shimPath), true);
  const script = fs.readFileSync(scriptPath, "utf-8");
  const shimSource = fs.readFileSync(shimPath, "utf-8");

  assert.match(shimSource, /qq_magic_napi_register/);
  assert.match(shimSource, /napi_module_register/);
  assert.match(script, /napcat-qqmagic-shim\.c/);
  assert.match(script, /libnapcat-qqmagic\.so/);
  assert.match(script, /LD_PRELOAD/);
  assert.match(script, /libgnutls\.so\.30/);
});

test("NapCat launcher resolves Linux bot config paths and per-instance overrides", () => {
  process.env.NAPCAT_LAUNCHER_TEST = "1";
  const { getInstanceConfig } = require("../../scripts/napcat-launcher.cjs");

  const qqbot = getInstanceConfig("qqbot", { platform: "linux", env: {} });
  assert.equal(qqbot.botConfig, "/opt/napcat_bots/qqbot/config.yaml");

  const onlyGroup = getInstanceConfig("only-group-bot", {
    platform: "linux",
    env: { NAPCAT_ONLY_GROUP_BOT_CONFIG: "/srv/only/config.yaml" },
  });
  assert.equal(onlyGroup.botConfig, "/srv/only/config.yaml");
});

test("NapCat launcher detects shell dependency paths", () => {
  process.env.NAPCAT_LAUNCHER_TEST = "1";
  const {
    ensureNapcatWorkspaceConfig,
    hasNapcatShellDependency,
    napcatShellDir,
    napcatShellDistPath,
    napcatWorkspacePath,
  } = require("../../scripts/napcat-launcher.cjs");

  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "napcat-root-"));
  assert.equal(napcatShellDir(rootDir), path.join(rootDir, "packages", "napcat-shell"));
  assert.equal(
    napcatShellDistPath(rootDir),
    path.join(rootDir, "packages", "napcat-shell", "dist", "napcat.mjs")
  );
  assert.equal(napcatWorkspacePath(rootDir), path.join(rootDir, "pnpm-workspace.yaml"));
  assert.equal(hasNapcatShellDependency(rootDir, "express"), false);

  fs.mkdirSync(path.join(rootDir, "packages", "napcat-shell", "node_modules", "express"), { recursive: true });
  assert.equal(hasNapcatShellDependency(rootDir, "express"), true);

  ensureNapcatWorkspaceConfig(rootDir);
  assert.match(fs.readFileSync(path.join(rootDir, "pnpm-workspace.yaml"), "utf-8"), /dangerouslyAllowAllBuilds:\s*true/);
});
