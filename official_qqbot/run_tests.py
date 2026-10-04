"""Run offline regression tests with disposable configuration and state."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="qqbot-tests-") as temp:
        target = Path(temp) / "official_qqbot"
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(
            ".venv", "node_modules", "data", "logs", "__pycache__", ".pytest_cache",
            "config.yaml", "config.yaml.*", "*.log", ".env",
        ))
        shutil.copyfile(source / "config.example.yaml", target / "config.yaml")
        env = {key: value for key, value in os.environ.items() if not key.startswith((
            "QQ_", "AI_", "IMAGE_AI_", "CONTROL_API_", "BOT_CONTROL_", "ADMIN_CONTROL_",
            "DATABASE_URL", "BOT_CONFIG_", "DASHBOARD_", "SAUTH_", "PY_BRIDGE_",
        ))}
        env["PYTHONIOENCODING"] = "utf-8"
        env["NODE_PATH"] = str(source / "koishi-bridge" / "node_modules")
        return subprocess.call(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", *sys.argv[1:]],
            cwd=target, env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
