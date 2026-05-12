const fs = require("node:fs");
const path = require("node:path");

class PluginRegistry {
  constructor(options) {
    this.pluginsDir = options.pluginsDir;
    this.statePath = options.statePath;
    this.builtinPlugins = options.builtinPlugins || [];
  }

  readState() {
    try {
      if (fs.existsSync(this.statePath)) {
        const parsed = JSON.parse(fs.readFileSync(this.statePath, "utf-8"));
        return parsed && typeof parsed === "object" ? parsed : {};
      }
    } catch {
      return {};
    }
    return {};
  }

  writeState(state) {
    fs.mkdirSync(path.dirname(this.statePath), { recursive: true });
    fs.writeFileSync(this.statePath, `${JSON.stringify(state, null, 2)}\n`, "utf-8");
  }

  list() {
    const state = this.readState();
    const builtin = this.builtinPlugins.map((plugin) => {
      const saved = state.plugins?.[plugin.id];
      const enabled =
        typeof saved?.enabled === "boolean" ? saved.enabled : plugin.enabled !== false;
      return {
        id: plugin.id,
        name: plugin.name || plugin.id,
        description: plugin.description || "",
        type: "builtin",
        entry: "",
        commands: Array.isArray(plugin.commands) ? plugin.commands : [],
        enabled,
        path: "handlers",
      };
    });

    const entries = fs.existsSync(this.pluginsDir)
      ? fs.readdirSync(this.pluginsDir, { withFileTypes: true })
      : [];
    const external = entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => {
        const manifestPath = path.join(this.pluginsDir, entry.name, "plugin.json");
        if (!fs.existsSync(manifestPath)) {
          return null;
        }
        try {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
          const id = manifest.id || entry.name;
          const saved = state.plugins?.[id];
          const enabled =
            typeof saved?.enabled === "boolean"
              ? saved.enabled
              : manifest.enabled !== false;
          return {
            id,
            name: manifest.name || id,
            description: manifest.description || "",
            type: manifest.type || "python",
            entry: manifest.entry || "",
            commands: Array.isArray(manifest.commands) ? manifest.commands : [],
            enabled,
            path: path.join(this.pluginsDir, entry.name),
          };
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => a.id.localeCompare(b.id));
    return [...builtin, ...external].sort((a, b) => a.id.localeCompare(b.id));
  }

  setEnabled(pluginId, enabled) {
    const plugins = this.list();
    if (!plugins.some((plugin) => plugin.id === pluginId)) {
      throw new Error(`Plugin not found: ${pluginId}`);
    }

    const state = this.readState();
    state.plugins = state.plugins || {};
    state.plugins[pluginId] = {
      ...(state.plugins[pluginId] || {}),
      enabled: Boolean(enabled),
      updatedAt: new Date().toISOString(),
    };
    this.writeState(state);
    return this.list().find((plugin) => plugin.id === pluginId);
  }
}

module.exports = { PluginRegistry };
