const assert = require("node:assert/strict");
const test = require("node:test");

const { canStartService, startDisabledReason } = require("../../web/serviceUi");

test("blocked services keep the start button clickable", () => {
  const service = {
    id: "qqbot",
    running: false,
    disabled: false,
    state: "blocked",
    health: {
      status: "closed",
      message: "127.0.0.1:3001 不可连接",
    },
  };

  assert.equal(canStartService(service), true);
  assert.equal(startDisabledReason(service), "");
});

test("running and disabled services still cannot be started", () => {
  assert.equal(canStartService({ running: true, disabled: false }), false);
  assert.equal(startDisabledReason({ running: true, disabled: false }), "服务已在运行");
  assert.equal(canStartService({ running: false, disabled: true }), false);
  assert.equal(startDisabledReason({ running: false, disabled: true }), "服务未配置");
});
