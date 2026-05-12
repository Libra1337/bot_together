const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { PluginRegistry } = require("../../server/pluginRegistry");

function withTempDir(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "qqbot-plugins-"));
  try {
    return fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("PluginRegistry lists manifests and persists enabled state", () => {
  withTempDir((dir) => {
    const pluginsDir = path.join(dir, "plugins");
    const statePath = path.join(dir, "plugins.json");
    fs.mkdirSync(path.join(pluginsDir, "hello"), { recursive: true });
    fs.writeFileSync(
      path.join(pluginsDir, "hello", "plugin.json"),
      JSON.stringify({
        id: "hello",
        name: "Hello",
        type: "python",
        entry: "plugin.py",
        commands: ["/hello"],
      })
    );

    const registry = new PluginRegistry({ pluginsDir, statePath });
    assert.deepEqual(
      registry.list().map((plugin) => ({
        id: plugin.id,
        enabled: plugin.enabled,
        type: plugin.type,
      })),
      [{ id: "hello", enabled: true, type: "python" }]
    );

    registry.setEnabled("hello", false);
    const reloaded = new PluginRegistry({ pluginsDir, statePath });
    assert.equal(reloaded.list()[0].enabled, false);
  });
});

test("PluginRegistry includes built-in official bot modules", () => {
  withTempDir((dir) => {
    const pluginsDir = path.join(dir, "plugins");
    const statePath = path.join(dir, "plugins.json");
    fs.mkdirSync(pluginsDir, { recursive: true });

    const registry = new PluginRegistry({
      pluginsDir,
      statePath,
      builtinPlugins: [
        {
          id: "builtin.nfa",
          name: "NFA",
          description: "获取 NFA Token",
          commands: ["nfa", "/nfa"],
        },
      ],
    });

    assert.deepEqual(
      registry.list().map((plugin) => ({
        id: plugin.id,
        type: plugin.type,
        enabled: plugin.enabled,
      })),
      [{ id: "builtin.nfa", type: "builtin", enabled: true }]
    );

    registry.setEnabled("builtin.nfa", false);
    assert.equal(registry.list()[0].enabled, false);
  });
});
