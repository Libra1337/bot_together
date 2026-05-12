const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { BotProcessManager } = require("../../server/botProcess");

test("BotProcessManager reports stopped before start", () => {
  const manager = new BotProcessManager({
    cwd: process.cwd(),
    command: process.execPath,
    args: ["-e", "setInterval(() => {}, 1000)"],
    stopTimeoutMs: 300,
  });

  const status = manager.getStatus();
  assert.equal(status.running, false);
  assert.equal(status.pid, null);
});

test("BotProcessManager starts and stops a child process", async () => {
  const manager = new BotProcessManager({
    cwd: process.cwd(),
    command: process.execPath,
    args: ["-e", "setInterval(() => {}, 1000)"],
  });

  const started = await manager.start();
  assert.equal(started.running, true);
  assert.equal(typeof started.pid, "number");

  const secondStart = await manager.start();
  assert.equal(secondStart.pid, started.pid);

  const stopped = await manager.stop();
  assert.equal(stopped.running, false);
  assert.equal(stopped.pid, null);
});
