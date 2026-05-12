const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

function sendJson(res, status, data, headers = {}) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    ...headers,
  });
  res.end(body);
}

function sendText(res, status, text, headers = {}) {
  res.writeHead(status, {
    "content-type": "text/plain; charset=utf-8",
    ...headers,
  });
  res.end(text);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error("Request body too large"));
        req.destroy();
      }
    });
    req.on("end", () => {
      if (!body) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function serveStatic(req, res, webDir) {
  const url = new URL(req.url, "http://localhost");
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === "/") pathname = "/index.html";
  const filePath = path.resolve(webDir, `.${pathname}`);
  const root = path.resolve(webDir);

  if (!filePath.startsWith(root)) {
    sendText(res, 403, "Forbidden");
    return;
  }

  const target = fs.existsSync(filePath) && fs.statSync(filePath).isFile()
    ? filePath
    : path.join(root, "index.html");

  if (!fs.existsSync(target)) {
    sendText(res, 404, "Not found");
    return;
  }

  const ext = path.extname(target);
  res.writeHead(200, {
    "content-type": MIME_TYPES[ext] || "application/octet-stream",
  });
  fs.createReadStream(target).pipe(res);
}

function toPublicConfig(config) {
  return {
    server: {
      host: config.server.host,
      port: config.server.port,
      publicUrl: config.server.publicUrl,
    },
    bot: {
      command: config.bot.command,
      entry: config.bot.entry,
      args: config.bot.args,
      cwd: config.bot.cwd,
    },
    paths: config.paths,
    services: (config.services || []).map((service) => ({
      id: service.id,
      name: service.name,
      kind: service.kind,
      command: service.command,
      entry: service.entry,
      args: service.args || [],
      cwd: service.cwd,
      webUrl: service.webUrl || "",
      disabled: Boolean(service.disabled),
      dependsOn: service.dependsOn || [],
      health: service.health
        ? {
            type: service.health.type,
            host: service.health.host,
            port: service.health.port,
          }
        : null,
    })),
  };
}

module.exports = {
  readJson,
  sendJson,
  sendText,
  serveStatic,
  toPublicConfig,
};
