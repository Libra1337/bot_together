import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceSecretExposureTest(unittest.TestCase):
    def test_runtime_credentials_are_not_nonempty_string_literals(self):
        protected_names = {
            "APP_SECRET",
            "BOT_TOKEN",
            "SAUTH_API_KEY",
            "SAUTH_ADMIN_TOKEN",
        }
        exposed = []

        for relative_path in ("_test_ws.py", "handlers/sauth.py"):
            path = ROOT / relative_path
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name) or target.id not in protected_names:
                        continue
                    if isinstance(node.value, ast.Constant) and node.value.value:
                        exposed.append(f"{relative_path}:{target.id}")

        self.assertEqual([], exposed)

    def test_deployment_example_declares_sauth_credentials(self):
        example = (
            ROOT / "deploy" / "ubuntu" / "koishi-bridge.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn("SAUTH_API_KEY=replace-with-sauth-api-key", example)
        self.assertIn("SAUTH_ADMIN_TOKEN=replace-with-sauth-admin-token", example)

    def test_deployment_example_uses_admin_token_placeholder(self):
        example = (
            ROOT / "deploy" / "ubuntu" / "koishi-bridge.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "ADMIN_CONTROL_TOKEN=replace-with-admin-control-token",
            example,
        )


if __name__ == "__main__":
    unittest.main()
