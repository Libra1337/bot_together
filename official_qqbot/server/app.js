const http = require("node:http");
const path = require("node:path");
const { clearSessionCookie, parseCookie, SessionStore, sessionCookie } = require("./auth");
const { ROOT_DIR, loadConfig, verifyPassword } = require("./config");
const { BUILTIN_PLUGINS } = require("./builtinPlugins");
const { PluginRegistry } = require("./pluginRegistry");
const { ServiceRegistry } = require("./serviceManager");
const { readJson, sendJson, sendText, serveStatic, toPublicConfig } = require("./httpUtils");

function createApp({ configPath } = {}) {
  const config = loadConfig(configPath);
  const resolveFromRoot = (value) =>
    value && path.isAbsolute(value) ? value : path.join(ROOT_DIR, value || ".");
  const runtimeConfig = {
    ...config,
    bot: {
      ...config.bot,
      cwd: resolveFromRoot(config.bot.cwd),
    },
    services: (config.services || []).map((service) => ({
      ...service,
      cwd: resolveFromRoot(service.cwd),
    })),
    paths: {
      ...config.paths,
      pluginsDir: resolveFromRoot(config.paths.pluginsDir),
      pluginState: resolveFromRoot(config.paths.pluginState),
      webDir: resolveFromRoot(config.paths.webDir),
    },
  };
  const sessions = new SessionStore();
  const serviceRegistry = new ServiceRegistry(runtimeConfig.services);
  const plugins = new PluginRegistry({
    pluginsDir: runtimeConfig.paths.pluginsDir,
    statePath: runtimeConfig.paths.pluginState,
    builtinPlugins: BUILTIN_PLUGINS,
  });

  function authenticate(req) {
    const cookies = parseCookie(req.headers.cookie || "");
    const token = cookies.qqbot_session || req.headers.authorization?.replace(/^Bearer\s+/i, "");
    return sessions.get(token);
  }

  function requireAuth(req, res) {
    const session = authenticate(req);
    if (!session) {
      sendJson(res, 401, { error: "Unauthorized" });
      return null;
    }
    return session;
  }

  async function route(req, res) {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);

    try {
      if (req.method === "POST" && url.pathname === "/api/login") {
        const body = await readJson(req);
        const user = config.auth.users.find((item) => item.username === body.username);
        if (!user || !verifyPassword(String(body.password || ""), user.passwordHash)) {
          sendJson(res, 401, { error: "用户名或密码不正确" });
          return;
        }
        const token = sessions.create(user.username);
        sendJson(
          res,
          200,
          { ok: true, user: { username: user.username, role: user.role || "admin" } },
          { "set-cookie": sessionCookie(token) }
        );
        return;
      }

      if (req.method === "POST" && url.pathname === "/api/logout") {
        const cookies = parseCookie(req.headers.cookie || "");
        sessions.delete(cookies.qqbot_session);
        sendJson(res, 200, { ok: true }, { "set-cookie": clearSessionCookie() });
        return;
      }

      if (url.pathname.startsWith("/api/")) {
        const session = requireAuth(req, res);
        if (!session) return;

        if (req.method === "GET" && url.pathname === "/api/me") {
          sendJson(res, 200, { username: session.username });
          return;
        }

        if (req.method === "GET" && url.pathname === "/api/status") {
          await serviceRegistry.checkHealth();
          const services = serviceRegistry.getStatus().services;
          const officialBot = services.find((service) => service.id === "official-bot") || services[0];
          sendJson(res, 200, {
            bot: officialBot,
            services,
            plugins: plugins.list(),
            config: toPublicConfig(config),
          });
          return;
        }

        if (req.method === "POST" && url.pathname === "/api/bot/start") {
          sendJson(res, 200, { bot: await serviceRegistry.start("official-bot") });
          return;
        }

        if (req.method === "POST" && url.pathname === "/api/bot/stop") {
          sendJson(res, 200, { bot: await serviceRegistry.stop("official-bot") });
          return;
        }

        const serviceAction = url.pathname.match(/^\/api\/services\/([^/]+)\/(start|stop)$/);
        if (req.method === "POST" && serviceAction) {
          const [, encodedId, action] = serviceAction;
          const id = decodeURIComponent(encodedId);
          const service =
            action === "start"
              ? await serviceRegistry.start(id)
              : await serviceRegistry.stop(id);
          sendJson(res, 200, { service });
          return;
        }

        const serviceLogs = url.pathname.match(/^\/api\/services\/([^/]+)\/logs$/);
        if (req.method === "GET" && serviceLogs) {
          const id = decodeURIComponent(serviceLogs[1]);
          const limit = Number(url.searchParams.get("limit") || 300);
          sendJson(res, 200, { logs: serviceRegistry.getLogs(limit, id) });
          return;
        }

        if (req.method === "GET" && url.pathname === "/api/logs") {
          const limit = Number(url.searchParams.get("limit") || 300);
          const serviceId = url.searchParams.get("serviceId") || "";
          sendJson(res, 200, { logs: serviceRegistry.getLogs(limit, serviceId) });
          return;
        }

        if (req.method === "GET" && url.pathname === "/api/logs/stream") {
          res.writeHead(200, {
            "content-type": "text/event-stream; charset=utf-8",
            "cache-control": "no-cache",
            connection: "keep-alive",
          });
          for (const entry of serviceRegistry.getLogs(100)) {
            res.write(`data: ${JSON.stringify(entry)}\n\n`);
          }
          const onLog = (entry) => res.write(`data: ${JSON.stringify(entry)}\n\n`);
          serviceRegistry.on("log", onLog);
          req.on("close", () => serviceRegistry.off("log", onLog));
          return;
        }

        if (req.method === "GET" && url.pathname === "/api/plugins") {
          sendJson(res, 200, { plugins: plugins.list() });
          return;
        }

        const pluginToggle = url.pathname.match(/^\/api\/plugins\/([^/]+)\/(enable|disable)$/);
        if (req.method === "POST" && pluginToggle) {
          const [, pluginId, action] = pluginToggle;
          sendJson(res, 200, {
            plugin: plugins.setEnabled(decodeURIComponent(pluginId), action === "enable"),
          });
          return;
        }

        sendJson(res, 404, { error: "Not found" });
        return;
      }

      if (req.method === "GET") {
        serveStatic(req, res, config.paths.webDir);
        return;
      }

      sendText(res, 405, "Method not allowed");
    } catch (error) {
      sendJson(res, error.statusCode || 500, { error: error.message });
    }
  }

  const server = http.createServer(route);
  return { config, server, serviceRegistry, plugins };
}

module.exports = { createApp };
