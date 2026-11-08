import importlib.util
import json
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hyprlauncher"
LOADER = SourceFileLoader("rice_launcher", str(SCRIPT))
SPEC = importlib.util.spec_from_loader("rice_launcher", LOADER)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class RiceLauncherTests(unittest.TestCase):
    def test_hakuspace_uses_rofi(self):
        with tempfile.TemporaryDirectory() as temporary:
            active = Path(temporary) / "active.json"
            active.write_text(json.dumps({"profile": "hakuspace"}), encoding="utf-8")

            self.assertEqual(
                launcher.launcher_command(active, ["--version"], "/usr/bin"),
                ["rofi", "-show", "drun"],
            )

    def test_other_rices_keep_the_system_hyprlauncher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / "active.json"
            active.write_text(json.dumps({"profile": "default"}), encoding="utf-8")
            executable_dir = root / "bin"
            executable_dir.mkdir()
            executable = executable_dir / "hyprlauncher"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)

            self.assertEqual(
                launcher.launcher_command(active, ["--help"], str(executable_dir)),
                [str(executable), "--help"],
            )

    def test_invalid_theme_state_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            active = Path(temporary) / "active.json"
            active.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid theme state"):
                launcher.launcher_command(active, [], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
