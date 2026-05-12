import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from plugin_runtime import PluginRuntime


def write_plugin(root: Path, plugin_id: str, manifest: dict, code: str = ""):
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"id": plugin_id, **manifest}, ensure_ascii=False),
        encoding="utf-8",
    )
    if code:
        (plugin_dir / manifest.get("entry", "plugin.py")).write_text(code, encoding="utf-8")


class PluginRuntimeTests(unittest.TestCase):
    def test_python_plugin_handles_matching_command(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_plugin(
                tmp_path,
                "hello",
                {"name": "Hello", "type": "python", "entry": "plugin.py", "commands": ["/hello"]},
                """
async def handle(event, api):
    return {"handled": True, "reply": "hello " + event["content"].split(maxsplit=1)[1]}
""",
            )

            runtime = PluginRuntime(str(tmp_path))
            result = asyncio.run(runtime.dispatch({"content": "/hello codex", "ctx": {}}))

            self.assertEqual(result, {"handled": True, "reply": "hello codex"})


    def test_disabled_plugin_is_skipped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_plugin(
                tmp_path,
                "hello",
                {"name": "Hello", "type": "python", "entry": "plugin.py", "commands": ["/hello"], "enabled": False},
                """
async def handle(event, api):
    return {"handled": True, "reply": "hello"}
""",
            )

            runtime = PluginRuntime(str(tmp_path))
            result = asyncio.run(runtime.dispatch({"content": "/hello", "ctx": {}}))

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
