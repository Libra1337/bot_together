const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT_DIR = path.resolve(__dirname, "..", "..", "..");

function readRequirements(filePath) {
  return fs
    .readFileSync(filePath, "utf16le")
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

test("qqbot requirements include Pillow", () => {
  const requirements = readRequirements(path.join(ROOT_DIR, "qqbot", "requirements.txt"));
  assert.ok(requirements.some((line) => /^Pillow(?:[=<].*)?$/.test(line)));
});

test("only-group-bot requirements include Pillow", () => {
  const requirements = readRequirements(path.join(ROOT_DIR, "only-group-bot", "requirements.txt"));
  assert.ok(requirements.some((line) => /^Pillow(?:[=<].*)?$/.test(line)));
});
