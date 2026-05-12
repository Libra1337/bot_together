const assert = require("node:assert/strict");
const net = require("node:net");
const test = require("node:test");

const { ManagedService, ServiceRegistry, probeTcp } = require("../../server/serviceManager");

function makeNodeService(id, code) {
  return {
    id,
    name: id,
    command: process.execPath,
    entry: "-e",
    args: [code],
    cwd: process.cwd(),
    env: {},
    stopTimeoutMs: 1000,
  };
}

test("probeTcp returns false for closed local port", async () => {
  const ok = await probeTcp("127.0.0.1", 9, 100);
  assert.equal(ok, false);
});

test("probeTcp returns true for open local port", async () => {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    const ok = await probeTcp("127.0.0.1", port, 500);
    assert.equal(ok, true);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("ManagedService starts, captures logs, and stops", async () => {
  const service = new ManagedService(
    makeNodeService("demo", "console.log('ready'); setInterval(() => {}, 1000);")
  );

  const status = await service.start();
  assert.equal(status.running, true);
  assert.equal(status.id, "demo");

  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.match(service.getLogs(20).map((entry) => entry.line).join("\n"), /ready/);

  const stopped = await service.stop();
  assert.equal(stopped.running, false);
});

test("ManagedService strips ANSI escape codes from logs", () => {
  const service = new ManagedService(makeNodeService("ansi", "setInterval(() => {}, 1000);"));

  service.appendLog("stdout", "\u001b[32minfo\u001b[39m 正常中文\n");

  assert.equal(service.getLogs(1)[0].line, "info 正常中文");
});

test("ManagedService status exposes service webUrl", () => {
  const service = new ManagedService({
    ...makeNodeService("web-service", "setInterval(() => {}, 1000);"),
    webUrl: "http://127.0.0.1:6199/webui?token=panel-qqbot",
  });

  assert.equal(service.getStatus().webUrl, "http://127.0.0.1:6199/webui?token=panel-qqbot");
});

test("ServiceRegistry starts service by id and streams service-tagged logs", async () => {
  const registry = new ServiceRegistry([
    makeNodeService("alpha", "console.log('alpha-log'); setInterval(() => {}, 1000);"),
  ]);

  const seen = [];
  registry.on("log", (entry) => seen.push(entry));
  await registry.start("alpha");
  await new Promise((resolve) => setTimeout(resolve, 100));

  assert.equal(registry.getStatus().services[0].id, "alpha");
  assert.equal(registry.getStatus().services[0].running, true);
  assert.ok(seen.some((entry) => entry.serviceId === "alpha"));

  await registry.stop("alpha");
});
