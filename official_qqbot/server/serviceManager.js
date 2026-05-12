const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const net = require("node:net");
const path = require("node:path");

function probeTcp(host, port, timeoutMs = 500) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    let settled = false;

    function finish(ok) {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(ok);
    }

    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

function cleanLogText(value) {
  return String(value).replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "");
}

class ManagedService extends EventEmitter {
  constructor(options) {
    super();
    this.id = options.id;
    this.name = options.name || options.id;
    this.kind = options.kind || "process";
    this.cwd = options.cwd || process.cwd();
    this.command = options.command;
    this.entry = options.entry || "";
    this.args = options.args || [];
    this.env = options.env || {};
    this.webUrl = options.webUrl || "";
    this.health = options.health || null;
    this.dependsOn = options.dependsOn || [];
    this.disabled = Boolean(options.disabled);
    this.requireHealthyBeforeStart = Boolean(options.requireHealthyBeforeStart);
    this.stopTimeoutMs = options.stopTimeoutMs || 8000;
    this.maxLogs = options.maxLogs || 1000;
    this.child = null;
    this.startedAt = null;
    this.exitedAt = null;
    this.lastExit = null;
    this.logs = [];
    this.healthState = {
      status: this.health ? "unknown" : "none",
      checkedAt: null,
      message: this.health ? "未检查" : "未配置健康检查",
    };
  }

  get spawnArgs() {
    return this.entry ? [this.entry, ...this.args] : this.args;
  }

  getStatus() {
    const running = Boolean(this.child && this.child.exitCode === null);
    const blocked =
      !running &&
      this.requireHealthyBeforeStart &&
      this.healthState.status === "closed";
    return {
      id: this.id,
      name: this.name,
      kind: this.kind,
      disabled: this.disabled,
      running,
      state: this.disabled ? "disabled" : running ? "running" : blocked ? "blocked" : "stopped",
      pid: running ? this.child.pid : null,
      startedAt: this.startedAt,
      uptimeSeconds:
        running && this.startedAt
          ? Math.floor((Date.now() - new Date(this.startedAt).getTime()) / 1000)
          : 0,
      lastExit: this.lastExit,
      command: this.command,
      entry: this.entry,
      args: this.args,
      cwd: this.cwd,
      webUrl: this.webUrl,
      health: this.healthState,
      dependsOn: this.dependsOn,
    };
  }

  getLogs(limit = 300) {
    return this.logs.slice(-limit);
  }

  appendLog(stream, chunk) {
    const text = cleanLogText(Buffer.isBuffer(chunk) ? chunk.toString("utf-8") : chunk);
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      const entry = {
        ts: new Date().toISOString(),
        serviceId: this.id,
        serviceName: this.name,
        stream,
        line,
      };
      this.logs.push(entry);
      if (this.logs.length > this.maxLogs) {
        this.logs.splice(0, this.logs.length - this.maxLogs);
      }
      this.emit("log", entry);
    }
  }

  async checkHealth() {
    if (!this.health) {
      this.healthState = {
        status: "none",
        checkedAt: new Date().toISOString(),
        message: "未配置健康检查",
      };
      return this.healthState;
    }

    if (this.health.type !== "tcp") {
      this.healthState = {
        status: "unknown",
        checkedAt: new Date().toISOString(),
        message: `不支持的健康检查类型: ${this.health.type}`,
      };
      return this.healthState;
    }

    const host = this.health.host || "127.0.0.1";
    const port = Number(this.health.port);
    const ok = await probeTcp(host, port, this.health.timeoutMs || 500);
    this.healthState = {
      status: ok ? "open" : "closed",
      checkedAt: new Date().toISOString(),
      message: ok ? `${host}:${port} 可连接` : `${host}:${port} 不可连接`,
      type: "tcp",
      host,
      port,
    };
    return this.healthState;
  }

  async start() {
    if (this.disabled) {
      const error = new Error(`${this.name} 当前已禁用，请先在 data/panel.json 配置启动命令`);
      error.statusCode = 409;
      throw error;
    }

    if (this.child && this.child.exitCode === null) {
      return this.getStatus();
    }

    if (this.requireHealthyBeforeStart) {
      const health = await this.checkHealth();
      if (health.status !== "open") {
        const error = new Error(`${this.name} 依赖不可用：${health.message}`);
        error.statusCode = 409;
        throw error;
      }
    }

    this.exitedAt = null;
    this.lastExit = null;
    const child = spawn(this.command, this.spawnArgs, {
      cwd: path.resolve(this.cwd),
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
        ...this.env,
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });

    this.child = child;
    this.startedAt = new Date().toISOString();
    this.appendLog("system", `Started: ${this.command} ${this.spawnArgs.join(" ")}`);

    child.stdout.on("data", (chunk) => this.appendLog("stdout", chunk));
    child.stderr.on("data", (chunk) => this.appendLog("stderr", chunk));
    child.on("exit", (code, signal) => {
      this.exitedAt = new Date().toISOString();
      this.lastExit = { code, signal, at: this.exitedAt };
      if (this.child === child) {
        this.child = null;
      }
      this.appendLog("system", `Exited: code=${code} signal=${signal || ""}`);
      this.emit("status", this.getStatus());
    });
    child.on("error", (error) => {
      this.appendLog("system", `Failed to start: ${error.message}`);
      this.emit("status", this.getStatus());
    });

    await new Promise((resolve) => setTimeout(resolve, 25));
    this.emit("status", this.getStatus());
    return this.getStatus();
  }

  async stop() {
    if (!this.child || this.child.exitCode !== null) {
      return this.getStatus();
    }

    const child = this.child;
    this.appendLog("system", `Stopping PID ${child.pid}`);

    const exited = new Promise((resolve) => {
      child.once("exit", resolve);
    });

    child.kill("SIGTERM");

    const timeout = new Promise((resolve) => {
      setTimeout(() => resolve("timeout"), this.stopTimeoutMs);
    });

    const result = await Promise.race([exited, timeout]);
    if (result === "timeout" && child.exitCode === null) {
      this.appendLog("system", `Force killing PID ${child.pid}`);
      if (process.platform === "win32") {
        spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
      } else {
        child.kill("SIGKILL");
      }
      await exited;
    }

    this.emit("status", this.getStatus());
    return this.getStatus();
  }
}

class ServiceRegistry extends EventEmitter {
  constructor(services = []) {
    super();
    this.services = new Map();
    for (const serviceConfig of services) {
      const service = new ManagedService(serviceConfig);
      service.on("log", (entry) => this.emit("log", entry));
      service.on("status", (status) => this.emit("status", status));
      this.services.set(service.id, service);
    }
  }

  get(id) {
    const service = this.services.get(id);
    if (!service) {
      throw new Error(`未知服务: ${id}`);
    }
    return service;
  }

  async checkHealth() {
    await Promise.all([...this.services.values()].map((service) => service.checkHealth()));
    return this.getStatus();
  }

  getStatus() {
    return {
      services: [...this.services.values()].map((service) => service.getStatus()),
    };
  }

  getLogs(limit = 300, serviceId = "") {
    if (serviceId) {
      return this.get(serviceId).getLogs(limit);
    }

    return [...this.services.values()]
      .flatMap((service) => service.getLogs(limit))
      .sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime())
      .slice(-limit);
  }

  async start(id) {
    return this.get(id).start();
  }

  async stop(id) {
    return this.get(id).stop();
  }
}

module.exports = { ManagedService, ServiceRegistry, probeTcp, cleanLogText };
