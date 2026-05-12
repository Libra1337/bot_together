const { EventEmitter } = require("node:events");
const { spawn } = require("node:child_process");
const path = require("node:path");

class BotProcessManager extends EventEmitter {
  constructor(options) {
    super();
    this.cwd = options.cwd || process.cwd();
    this.command = options.command;
    this.entry = options.entry || "";
    this.args = options.args || [];
    this.env = options.env || {};
    this.stopTimeoutMs = options.stopTimeoutMs || 8000;
    this.child = null;
    this.startedAt = null;
    this.exitedAt = null;
    this.lastExit = null;
    this.logs = [];
    this.maxLogs = options.maxLogs || 1000;
  }

  get spawnArgs() {
    return this.entry ? [this.entry, ...this.args] : this.args;
  }

  getStatus() {
    const running = Boolean(this.child && this.child.exitCode === null);
    return {
      running,
      pid: running ? this.child.pid : null,
      startedAt: this.startedAt,
      uptimeSeconds:
        running && this.startedAt
          ? Math.floor((Date.now() - new Date(this.startedAt).getTime()) / 1000)
          : 0,
      lastExit: this.lastExit,
    };
  }

  getLogs(limit = 300) {
    return this.logs.slice(-limit);
  }

  appendLog(stream, chunk) {
    const text = chunk.toString();
    for (const line of text.split(/\r?\n/)) {
      if (!line) continue;
      const entry = {
        ts: new Date().toISOString(),
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

  async start() {
    if (this.child && this.child.exitCode === null) {
      return this.getStatus();
    }

    this.exitedAt = null;
    this.lastExit = null;
    const child = spawn(this.command, this.spawnArgs, {
      cwd: this.cwd,
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

  static fromConfig(config) {
    const bot = config.bot || {};
    return new BotProcessManager({
      cwd: bot.cwd ? path.resolve(bot.cwd) : process.cwd(),
      command: bot.command,
      entry: bot.entry,
      args: bot.args || [],
      env: bot.env || {},
      stopTimeoutMs: bot.stopTimeoutMs || 8000,
    });
  }
}

module.exports = { BotProcessManager };
