import importlib.util
import io
import json
import os
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "theme-switcher"
LOADER = SourceFileLoader("theme_switcher", str(SCRIPT))
SPEC = importlib.util.spec_from_loader("theme_switcher", LOADER)
switcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(switcher)
ORIGINAL_RELOAD_APPS = switcher.reload_apps
ORIGINAL_GET_SETTINGS = switcher.get_settings
ORIGINAL_APPLY_SETTINGS = switcher.apply_settings


class ThemeSwitcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        switcher.HOME = self.root / "home"
        switcher.HOME.mkdir()
        switcher.THEMES = self.root / "themes"
        switcher.STATE = self.root / "state"
        switcher.get_settings = lambda: {}
        switcher.apply_settings = lambda _settings: None
        switcher.reload_apps = lambda _paths: None
        switcher.HEALTH_CHECK_WAIT = 0

    def tearDown(self):
        self.temp.cleanup()

    def create_profile(self, name, files, paths):
        directory = switcher.THEMES / name
        for relative, content in files.items():
            path = directory / "home" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "theme.json").write_text(json.dumps({
            "format": 1,
            "id": name,
            "name": name,
            "paths": paths,
            "settings": {},
            "health_check": [],
        }), encoding="utf-8")

    def test_list_json_outputs_profile_metadata(self):
        self.create_profile("dark-rice", {}, [])
        manifest_path = switcher.THEMES / "dark-rice/theme.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["name"] = "Dark Rice"
        manifest["settings"] = {"color_scheme": "prefer-dark"}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            switcher.cmd_list(SimpleNamespace(json=True))

        self.assertEqual(json.loads(output.getvalue()), [{
            "themeId": "dark-rice",
            "themeName": "Dark Rice",
            "kind": "profile",
            "colorScheme": "prefer-dark",
        }])

    def test_interactive_add_installs_compatible_github_profile_after_confirmation(self):
        def clone_repository(_source, destination, branch=None):
            profile_home = destination / "home/.config/waybar"
            profile_home.mkdir(parents=True)
            (profile_home / "config").write_text("{}", encoding="utf-8")
            (destination / "theme.json").write_text(json.dumps({
                "format": 1,
                "id": "night-rice",
                "name": "Night Rice",
                "paths": [".config/waybar"],
                "settings": {},
                "requires": ["python3"],
                "health_check": [],
            }), encoding="utf-8")

        with patch("builtins.input", side_effect=[
            "https://github.com/example/night-rice.git",
            "y",
        ]), patch.object(switcher, "clone_repository", side_effect=clone_repository):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                switcher.cmd_add_interactive(None)

        self.assertIn("compatibility check passed", output.getvalue())
        self.assertIn("Installed Rice profile: Night Rice (night-rice)", output.getvalue())
        self.assertTrue((switcher.THEMES / "night-rice/theme.json").is_file())
        self.assertFalse((switcher.STATE / "active.json").exists())
        self.assertEqual([item["id"] for item in switcher.list_profiles()], ["night-rice"])

    def test_interactive_add_rejects_incompatible_profile_before_confirmation(self):
        def clone_repository(_source, destination, branch=None):
            profile_home = destination / "home"
            profile_home.mkdir(parents=True)
            (destination / "theme.json").write_text(json.dumps({
                "format": 1,
                "id": "bad-rice",
                "name": "Bad Rice",
                "paths": ["../.ssh"],
                "settings": {},
            }), encoding="utf-8")

        with patch("builtins.input", return_value="https://github.com/example/bad-rice"), \
                patch.object(switcher, "clone_repository", side_effect=clone_repository):
            with self.assertRaisesRegex(switcher.ThemeError, "not suitable"):
                switcher.cmd_add_interactive(None)

        self.assertFalse((switcher.THEMES / "bad-rice").exists())

    def test_interactive_add_reports_missing_requirements_without_installing(self):
        missing_program = "__theme_switcher_missing_requirement_123__"

        def clone_repository(_source, destination, branch=None):
            profile_home = destination / "home/.config/waybar"
            profile_home.mkdir(parents=True)
            (profile_home / "config").write_text("{}", encoding="utf-8")
            (destination / "theme.json").write_text(json.dumps({
                "format": 1,
                "id": "needs-tool",
                "name": "Needs Tool",
                "paths": [".config/waybar"],
                "settings": {},
                "requires": [missing_program],
                "health_check": [],
            }), encoding="utf-8")

        with patch("builtins.input", return_value="https://github.com/example/needs-tool"), \
                patch.object(switcher, "clone_repository", side_effect=clone_repository):
            with self.assertRaisesRegex(switcher.ThemeError, missing_program):
                switcher.cmd_add_interactive(None)

        self.assertFalse((switcher.THEMES / "needs-tool").exists())

    def test_interactive_add_declines_install_without_writing_profile(self):
        def clone_repository(_source, destination, branch=None):
            profile_home = destination / "home/.config/waybar"
            profile_home.mkdir(parents=True)
            (profile_home / "config").write_text("{}", encoding="utf-8")
            (destination / "theme.json").write_text(json.dumps({
                "format": 1,
                "id": "declined-rice",
                "name": "Declined Rice",
                "paths": [".config/waybar"],
                "settings": {},
                "health_check": [],
            }), encoding="utf-8")

        with patch("builtins.input", side_effect=[
            "https://github.com/example/declined-rice",
            "n",
        ]), patch.object(switcher, "clone_repository", side_effect=clone_repository):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                switcher.cmd_add_interactive(None)

        self.assertIn("Installation cancelled", output.getvalue())
        self.assertFalse((switcher.THEMES / "declined-rice").exists())

    def test_theme_add_flag_is_parsed_as_interactive_add(self):
        args = switcher.build_parser().parse_args(["-add"])

        self.assertTrue(args.interactive_add)
        self.assertIsNone(args.command)

    def test_interactive_add_accepts_only_repository_level_public_github_urls(self):
        self.assertEqual(
            switcher.github_repository_name("https://github.com/example/night-rice.git"),
            "night-rice",
        )
        for source in (
            "http://github.com/example/night-rice",
            "https://github.com.evil/example/night-rice",
            "https://github.com/example/night-rice/tree/main",
        ):
            with self.subTest(source=source), self.assertRaises(switcher.ThemeError):
                switcher.github_repository_name(source)

    def test_repository_profile_discovery_requires_a_single_manifest(self):
        repository = self.root / "repository"
        nested_profile = repository / "rice/theme.json"
        nested_profile.parent.mkdir(parents=True)
        nested_profile.write_text("{}", encoding="utf-8")

        self.assertEqual(switcher.repository_profile_subdirectory(repository), "rice")

        other_profile = repository / "another/theme.json"
        other_profile.parent.mkdir(parents=True)
        other_profile.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(switcher.ThemeError, "multiple Rice profiles"):
            switcher.repository_profile_subdirectory(repository)

    def test_switch_restores_original_full_directory(self):
        active = switcher.HOME / ".config/rofi"
        active.mkdir(parents=True)
        (active / "config.rasi").write_text("original config", encoding="utf-8")
        (active / "extra.rasi").write_text("original extra", encoding="utf-8")
        self.create_profile(
            "current",
            {
                ".config/rofi/config.rasi": "saved config",
                ".config/rofi/extra.rasi": "saved extra",
            },
            [".config/rofi"],
        )
        self.create_profile(
            "new-look",
            {".config/rofi/config.rasi": "new config"},
            [".config/rofi"],
        )

        switcher.use_theme("new-look")
        self.assertEqual((active / "config.rasi").read_text(), "new config")
        self.assertTrue(active.is_symlink())
        self.assertEqual(
            active.resolve(),
            (switcher.THEMES / "new-look/home/.config/rofi").resolve(),
        )
        self.assertFalse((active / "extra.rasi").exists())

        switcher.use_theme("current")
        self.assertEqual((active / "config.rasi").read_text(), "saved config")
        self.assertEqual((active / "extra.rasi").read_text(), "saved extra")

    def test_switching_partial_theme_restores_omitted_components(self):
        rofi = switcher.HOME / ".config/rofi"
        rofi.mkdir(parents=True)
        (rofi / "config.rasi").write_text("base", encoding="utf-8")
        self.create_profile(
            "current",
            {".config/rofi/config.rasi": "base"},
            [".config/rofi"],
        )
        self.create_profile(
            "bar-only",
            {".config/waybar/style.css": "new bar"},
            [".config/waybar/style.css"],
        )

        switcher.use_theme("bar-only")
        self.assertEqual((rofi / "config.rasi").read_text(), "base")
        self.assertEqual(
            (switcher.HOME / ".config/waybar/style.css").read_text(),
            "new bar",
        )

    def test_undo_restores_the_previous_theme_and_state(self):
        self.create_profile("first", {".config/rofi/config": "first"}, [".config/rofi"])
        self.create_profile("second", {".config/rofi/config": "second"}, [".config/rofi"])

        switcher.use_theme("first")
        switcher.use_theme("second")
        switcher.cmd_undo(None)

        rofi = switcher.HOME / ".config/rofi"
        self.assertEqual((rofi / "config").read_text(), "first")
        self.assertEqual(rofi.resolve(), (switcher.THEMES / "first/home/.config/rofi").resolve())
        self.assertEqual(
            json.loads((switcher.STATE / "active.json").read_text())["profile"],
            "first",
        )

    def test_use_current_restores_original_files(self):
        original = switcher.HOME / ".config/rofi/config"
        original.parent.mkdir(parents=True)
        original.write_text("original", encoding="utf-8")
        self.create_profile("dark", {".config/rofi/config": "dark"}, [".config/rofi"])

        switcher.use_theme("dark")
        switcher.use_theme("current")

        self.assertEqual(original.read_text(), "original")
        self.assertFalse((switcher.STATE / "active.json").exists())

    def test_profile_preserves_personal_hyprland_configuration(self):
        personal = switcher.HOME / ".config/hypr/hyprland.lua"
        personal.parent.mkdir(parents=True)
        personal.write_text("personal keybindings", encoding="utf-8")
        self.create_profile(
            "rice",
            {
                ".config/hypr/hyprland.lua": "rice keybindings",
                ".config/hypr/hypridle.conf": "rice idle config",
            },
            [".config/hypr"],
        )

        switcher.use_theme("rice")

        self.assertEqual(personal.read_text(), "personal keybindings")
        self.assertEqual(
            (switcher.THEMES / "rice/home/.config/hypr/hyprland.lua").read_text(),
            "rice keybindings",
        )
        self.assertIn(
            ".config/hypr/hyprland.lua",
            json.loads((switcher.STATE / "active.json").read_text())["excludes"],
        )

    def test_profile_can_change_gtk_theme_without_changing_user_font(self):
        switcher.get_settings = lambda: {
            "gtk_font": "Adwaita Sans 11",
            "gtk_theme": "Original",
        }
        applied = []
        switcher.apply_settings = lambda values: applied.append(dict(values))
        self.create_profile(
            "gtk-rice",
            {
                ".config/gtk-3.0/settings.ini": (
                    "[Settings]\n"
                    "gtk-theme-name=RiceTheme\n"
                    "gtk-font-name=Rice Font 10\n"
                ),
            },
            [".config/gtk-3.0"],
        )
        manifest_path = switcher.THEMES / "gtk-rice/theme.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["settings"] = {
            "gtk_theme": "RiceTheme",
            "gtk_font": "Rice Font 10",
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        switcher.use_theme("gtk-rice")

        runtime_settings = switcher.HOME / ".config/gtk-3.0/settings.ini"
        settings_text = runtime_settings.read_text(encoding="utf-8")
        self.assertIn("gtk-theme-name=RiceTheme", settings_text)
        self.assertIn("gtk-font-name=Adwaita Sans 11", settings_text)
        self.assertNotIn(
            "gtk-font-name=Adwaita Sans 11",
            (switcher.THEMES / "gtk-rice/home/.config/gtk-3.0/settings.ini")
            .read_text(encoding="utf-8"),
        )
        self.assertEqual(applied[-1]["gtk_theme"], "RiceTheme")
        self.assertEqual(applied[-1]["gtk_font"], "Adwaita Sans 11")

    def test_get_settings_falls_back_to_live_gsettings(self):
        expected = {
            "gtk-theme": "'Hikaide'",
            "icon-theme": "'Hikaide-Symbols'",
            "cursor-theme": "'Haku-Dark'",
            "font-name": "'Adwaita Sans 11'",
            "color-scheme": "'prefer-dark'",
        }

        def fake_run(command, **_kwargs):
            return SimpleNamespace(
                returncode=0,
                stdout=expected[command[-1]],
                stderr="",
            )

        with patch.object(switcher, "get_settings", ORIGINAL_GET_SETTINGS), \
             patch.object(switcher.shutil, "which", return_value="/usr/bin/gsettings"), \
             patch.object(switcher.subprocess, "run", side_effect=fake_run):
            settings = switcher.get_settings()

        self.assertEqual(settings, {
            "gtk_theme": "Hikaide",
            "icon_theme": "Hikaide-Symbols",
            "cursor_theme": "Haku-Dark",
            "gtk_font": "Adwaita Sans 11",
            "color_scheme": "prefer-dark",
        })

    def test_apply_settings_updates_live_gsettings_and_settings_files(self):
        settings = {
            "gtk_theme": "Hikaide",
            "icon_theme": "Hikaide-Symbols",
            "cursor_theme": "Haku-Dark",
            "gtk_font": "Adwaita Sans 11",
        }
        with patch.object(switcher, "apply_settings", ORIGINAL_APPLY_SETTINGS), \
             patch.object(switcher.shutil, "which", return_value="/usr/bin/gsettings"), \
             patch.object(switcher.subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
            switcher.apply_settings(settings)

        gtk3 = (switcher.HOME / ".config/gtk-3.0/settings.ini").read_text()
        self.assertIn("gtk-theme-name=Hikaide", gtk3)
        self.assertIn("gtk-icon-theme-name=Hikaide-Symbols", gtk3)
        self.assertIn("gtk-cursor-theme-name=Haku-Dark", gtk3)
        self.assertIn("gtk-font-name=Adwaita Sans 11", gtk3)
        self.assertEqual(run.call_count, 4)

    def test_profile_preserves_kitty_font_and_arabic_symbol_mapping(self):
        personal = switcher.HOME / ".config/kitty/kitty.conf"
        personal.parent.mkdir(parents=True)
        personal.write_text(
            "font_family monospace\n"
            "font_size 11\n"
            "symbol_map U+0600-U+06FF Noto Sans Arabic\n"
            "shell dosu\n",
            encoding="utf-8",
        )
        self.create_profile(
            "kitty-rice",
            {
                ".config/kitty/kitty.conf": (
                    "font_family Rice Nerd Font\n"
                    "font_size 18\n"
                    "background #1e1e2e\n"
                ),
            },
            [".config/kitty"],
        )

        switcher.use_theme("kitty-rice")

        active = personal.read_text(encoding="utf-8")
        self.assertIn("font_family monospace", active)
        self.assertIn("font_size 11", active)
        self.assertIn("symbol_map U+0600-U+06FF Noto Sans Arabic", active)
        self.assertIn("shell dosu", active)
        self.assertIn("background #1e1e2e", active)
        self.assertNotIn("font_family Rice Nerd Font", active)
        self.assertIn(
            "font_family Rice Nerd Font",
            (switcher.THEMES / "kitty-rice/home/.config/kitty/kitty.conf")
            .read_text(encoding="utf-8"),
        )

    def test_partial_profile_baselines_the_whole_application_directory(self):
        waybar = switcher.HOME / ".config/waybar"
        waybar.mkdir(parents=True)
        (waybar / "style.css").write_text("original style", encoding="utf-8")
        (waybar / "config").write_text("original config", encoding="utf-8")
        self.create_profile(
            "overlay",
            {".config/waybar/style.css": "overlay style"},
            [".config/waybar/style.css"],
        )
        self.create_profile(
            "other-app",
            {".config/kitty/kitty.conf": "kitty config"},
            [".config/kitty"],
        )

        switcher.use_theme("overlay")
        switcher.use_theme("other-app")

        self.assertEqual((waybar / "style.css").read_text(), "original style")
        self.assertEqual((waybar / "config").read_text(), "original config")

    def test_rejects_paths_outside_home(self):
        with self.assertRaises(switcher.ThemeError):
            switcher.safe_home_path("../.ssh")
        self.assertEqual(switcher.safe_home_path(".nanorc"), switcher.HOME / ".nanorc")

    def test_requires_missing_programs_fail_before_switch(self):
        self.create_profile("needs-swww", {".config/hypr/config": "x"}, [".config/hypr"])
        manifest_path = switcher.THEMES / "needs-swww/theme.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["requires"] = ["swww"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with patch.object(switcher.shutil, "which", return_value=None):
            with self.assertRaisesRegex(switcher.ThemeError, "swww"):
                switcher.apply_profile("needs-swww")
            switcher.check_requirements("needs-swww", manifest, force=True)
        self.assertFalse((switcher.STATE / "active.json").exists())
        self.assertFalse((switcher.HOME / ".config/hypr").exists())

    def test_manifest_extra_paths_are_opt_in_and_allowlisted(self):
        with self.assertRaises(switcher.ThemeError):
            switcher.safe_home_path(".local/bin")
        self.assertEqual(
            switcher.safe_home_path(
                ".local/bin", extra_paths=[".local/bin"]
            ),
            switcher.HOME / ".local/bin",
        )
        with self.assertRaisesRegex(switcher.ThemeError, "extra_paths"):
            switcher.safe_home_path(
                ".ssh", extra_paths=[".ssh"]
            )

    def test_apply_stops_old_rice_then_starts_new_rice_after_reload(self):
        self.create_profile("old", {".config/hypr/config": "old"}, [".config/hypr"])
        self.create_profile("new", {".config/hypr/config": "new"}, [".config/hypr"])
        old_manifest = switcher.THEMES / "old/theme.json"
        new_manifest = switcher.THEMES / "new/theme.json"
        switcher.use_theme("old")
        old_data = json.loads(old_manifest.read_text())
        old_data.update({"stop": ["waybar"], "start": ["old-bar"]})
        old_manifest.write_text(json.dumps(old_data), encoding="utf-8")
        new_data = json.loads(new_manifest.read_text())
        new_data.update({"stop": ["quickshell"], "start": ["qs -c rice"]})
        new_data["health_check"] = []
        new_manifest.write_text(json.dumps(new_data), encoding="utf-8")

        events = []
        switcher.reload_apps = lambda paths: events.append(("reload", list(paths)))

        def fake_run(argv, **_kwargs):
            events.append(("run", argv))
            return subprocess.CompletedProcess(argv, 1, stderr=b"")

        def fake_popen(argv, **_kwargs):
            events.append(("start", argv))

        with patch.object(switcher.subprocess, "run", side_effect=fake_run), \
                patch.object(switcher.subprocess, "Popen", side_effect=fake_popen), \
                patch.object(switcher.time, "sleep"):
            switcher.apply_profile("new")

        self.assertEqual(events[0][0], "reload")
        self.assertEqual(events[1], ("run", ["pgrep", "-x", "waybar"]))
        self.assertEqual(events[2], ("start", ["qs", "-c", "rice"]))

    def test_failed_switch_restarts_previous_rice_processes(self):
        self.create_profile("old", {".config/hypr/config": "old"}, [".config/hypr"])
        self.create_profile("new", {".config/hypr/config": "new"}, [".config/hypr"])
        old_manifest = switcher.THEMES / "old/theme.json"
        new_manifest = switcher.THEMES / "new/theme.json"
        old_data = json.loads(old_manifest.read_text())
        old_data["health_check"] = []
        old_manifest.write_text(json.dumps(old_data), encoding="utf-8")
        switcher.use_theme("old")
        old_data["start"] = ["old-bar"]
        old_data["stop"] = ["waybar"]
        old_manifest.write_text(json.dumps(old_data), encoding="utf-8")
        new_data = json.loads(new_manifest.read_text())
        new_data.update({
            "stop": ["quickshell"],
            "start": ["new-bar"],
            "health_check": ["fail-check"],
        })
        new_manifest.write_text(json.dumps(new_data), encoding="utf-8")

        events = []
        switcher.reload_apps = lambda paths: events.append(("reload", list(paths)))

        def fake_run(argv, **_kwargs):
            events.append(("run", argv))
            code = 1 if argv[0] == "fail-check" else 1
            return subprocess.CompletedProcess(argv, code, stderr=b"")

        def fake_popen(argv, **_kwargs):
            events.append(("start", argv))

        with patch.object(switcher.subprocess, "run", side_effect=fake_run), \
                patch.object(switcher.subprocess, "Popen", side_effect=fake_popen), \
                patch.object(switcher.time, "sleep"):
            with self.assertRaisesRegex(switcher.ThemeError, "health check failed"):
                switcher.apply_profile("new")

        self.assertEqual(events[-1], ("start", ["old-bar"]))
        active = json.loads((switcher.STATE / "active.json").read_text())
        self.assertEqual(active["profile"], "old")
        self.assertEqual(
            (switcher.HOME / ".config/hypr/config").read_text(), "old"
        )

    def test_use_rolls_back_if_hyprland_rejects_the_new_config(self):
        self.create_profile("old", {".config/hypr/config": "old"}, [".config/hypr"])
        self.create_profile("new", {".config/hypr/config": "new"}, [".config/hypr"])
        switcher.use_theme("old")

        def reload_config(_paths):
            if (switcher.HOME / ".config/hypr/config").read_text() == "new":
                raise switcher.ThemeError(
                    "Hyprland configuration reported errors: legacy syntax"
                )

        switcher.reload_apps = reload_config
        with self.assertRaisesRegex(switcher.ThemeError, "legacy syntax"):
            switcher.use_theme("new")

        self.assertEqual(
            (switcher.HOME / ".config/hypr/config").read_text(), "old"
        )
        active = json.loads((switcher.STATE / "active.json").read_text())
        self.assertEqual(active["profile"], "old")

    def test_failed_first_switch_reloads_restored_baseline(self):
        original = switcher.HOME / ".config/hypr/hyprland.lua"
        original.parent.mkdir(parents=True)
        original.write_text("original Lua config", encoding="utf-8")
        self.create_profile(
            "legacy",
            {".config/hypr/hyprland.conf": "legacy config"},
            [".config/hypr"],
        )
        reloads = []

        def reload_config(paths):
            reloads.append(list(paths))
            if len(reloads) == 1:
                raise switcher.ThemeError("Hyprland rejected legacy config")

        switcher.reload_apps = reload_config
        with self.assertRaisesRegex(switcher.ThemeError, "rejected legacy config"):
            switcher.use_theme("legacy")

        self.assertEqual(reloads, [[".config/hypr"], [".config/hypr"]])
        self.assertEqual(original.read_text(encoding="utf-8"), "original Lua config")
        self.assertFalse((original.parent / "hyprland.conf").exists())
        self.assertFalse((switcher.STATE / "active.json").exists())

    def test_reload_apps_rejects_hyprland_config_diagnostics(self):
        results = [
            subprocess.CompletedProcess(["hyprctl", "reload"], 0, stdout=b"ok"),
            subprocess.CompletedProcess(
                ["hyprctl", "configerrors"],
                0,
                stdout=b"cannot open hyprland.lua: No such file",
            ),
        ]
        with patch.object(switcher.subprocess, "run", side_effect=results):
            with self.assertRaisesRegex(
                switcher.ThemeError, "Hyprland configuration reported errors"
            ):
                ORIGINAL_RELOAD_APPS([".config/hypr"])

    def test_dry_run_shows_stop_and_start_without_running_commands(self):
        self.create_profile("old", {".config/hypr/config": "old"}, [".config/hypr"])
        self.create_profile("new", {".config/hypr/config": "new"}, [".config/hypr"])
        old_manifest = switcher.THEMES / "old/theme.json"
        new_manifest = switcher.THEMES / "new/theme.json"
        old_data = json.loads(old_manifest.read_text())
        old_data["stop"] = ["waybar"]
        old_manifest.write_text(json.dumps(old_data), encoding="utf-8")
        new_data = json.loads(new_manifest.read_text())
        new_data["start"] = ["quickshell -c rice"]
        new_manifest.write_text(json.dumps(new_data), encoding="utf-8")
        switcher.use_theme("old")

        output = io.StringIO()
        with patch.object(switcher.subprocess, "run") as run, \
                patch.object(switcher.subprocess, "Popen") as popen, \
                contextlib.redirect_stdout(output):
            switcher.apply_profile("new", dry_run=True)

        self.assertIn("waybar", output.getvalue())
        self.assertIn("quickshell -c rice", output.getvalue())
        run.assert_not_called()
        popen.assert_not_called()

    def test_use_current_stops_active_rice_without_starting_baseline_processes(self):
        self.create_profile("active", {".config/hypr/config": "rice"}, [".config/hypr"])
        switcher.use_theme("active")
        manifest_path = switcher.THEMES / "active/theme.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["stop"] = ["waybar"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with patch.object(
            switcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["pgrep"], 1, stderr=b""),
        ) as run, patch.object(switcher.subprocess, "Popen") as popen, \
                patch.object(switcher.os, "kill") as kill:
            switcher.use_theme("current")

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["pgrep", "-x", "waybar"])
        popen.assert_not_called()
        kill.assert_not_called()
        self.assertFalse((switcher.STATE / "active.json").exists())

    def test_stop_rice_signals_only_exact_process_ids(self):
        signals = []

        def fake_kill(pid, signum):
            signals.append((pid, signum))
            if signum == 0:
                raise ProcessLookupError

        with patch.object(
            switcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["pgrep"], 0, stdout=b"123\n456\n"
            ),
        ) as run, patch.object(switcher.os, "kill", side_effect=fake_kill):
            switcher.stop_rice({"stop": ["waybar"]})

        run.assert_called_once_with(
            ["pgrep", "-x", "waybar"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            signals,
            [
                (123, switcher.signal.SIGTERM),
                (123, 0),
                (456, switcher.signal.SIGTERM),
                (456, 0),
            ],
        )

    def test_preview_and_doctor_report_lifecycle_and_missing_requirements(self):
        self.create_profile("sample-rice", {".config/hypr/config": "x"}, [".config/hypr"])
        manifest_path = switcher.THEMES / "sample-rice/theme.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.update({
            "requires": ["missing-program"],
            "stop": ["waybar"],
            "start": ["qs -c sample"],
        })
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            switcher.cmd_preview(SimpleNamespace(name="sample-rice"))
        preview = output.getvalue()
        self.assertIn("Requires: missing-program", preview)
        self.assertIn("Stop: waybar", preview)
        self.assertIn("Start: qs -c sample", preview)
        self.assertIn(".config/hypr", preview)

        output = io.StringIO()
        with patch.object(switcher.shutil, "which", return_value=None), \
                patch.object(
                    switcher.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(["hyprctl"], 0),
                ), contextlib.redirect_stdout(output):
            switcher.cmd_doctor(None)
        self.assertIn("theme sample-rice missing requires: missing-program", output.getvalue())

    def test_restart_session_requires_an_explicit_confirmation(self):
        args = SimpleNamespace(
            name="rice",
            force=False,
            restart_session=True,
        )
        with patch.object(switcher, "use_theme") as use, \
                patch("builtins.input", return_value="no"), \
                patch.object(switcher.subprocess, "run") as run:
            switcher.cmd_use(args)
        use.assert_called_once_with("rice", force=False)
        run.assert_not_called()

        with patch.object(switcher, "use_theme") as use, \
                patch("builtins.input", return_value="yes"), \
                patch.object(
                    switcher.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(["hyprctl"], 0),
                ) as run:
            switcher.cmd_use(args)
        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0], ["hyprctl", "dispatch", "exit"]
        )

    def test_undo_stops_current_rice_and_restarts_previous_rice(self):
        self.create_profile("old", {".config/hypr/config": "old"}, [".config/hypr"])
        self.create_profile("new", {".config/hypr/config": "new"}, [".config/hypr"])
        old_manifest_path = switcher.THEMES / "old/theme.json"
        new_manifest_path = switcher.THEMES / "new/theme.json"
        switcher.use_theme("old")
        old_data = json.loads(old_manifest_path.read_text())
        old_data.update({"stop": ["waybar"], "start": ["old-bar"]})
        old_manifest_path.write_text(json.dumps(old_data), encoding="utf-8")
        new_data = json.loads(new_manifest_path.read_text())
        new_data.update({"stop": ["quickshell"], "start": ["new-bar"], "health_check": []})
        new_manifest_path.write_text(json.dumps(new_data), encoding="utf-8")

        events = []
        switcher.reload_apps = lambda paths: events.append(("reload", list(paths)))

        def fake_run(argv, **_kwargs):
            events.append(("run", argv))
            return subprocess.CompletedProcess(argv, 1, stderr=b"")

        def fake_popen(argv, **_kwargs):
            events.append(("start", argv))

        with patch.object(switcher.subprocess, "run", side_effect=fake_run), \
                patch.object(switcher.subprocess, "Popen", side_effect=fake_popen):
            switcher.apply_profile("new")
            events.clear()
            switcher.cmd_undo(None)

        self.assertIn(("run", ["pgrep", "-x", "quickshell"]), events)
        self.assertEqual(events[-1], ("start", ["old-bar"]))
        active = json.loads((switcher.STATE / "active.json").read_text())
        self.assertEqual(active["profile"], "old")

    def test_import_adds_multiple_application_configs_without_applying(self):
        source = self.root
        (source / "hypr").mkdir(parents=True)
        (source / "hypr/hyprland.conf").write_text("hypr config", encoding="utf-8")
        (source / "waybar").mkdir()
        (source / "waybar/style.css").write_text("bar style", encoding="utf-8")
        (source / ".config/mozilla").mkdir(parents=True)
        (source / ".config/mozilla/profiles.ini").write_text("private profile data", encoding="utf-8")
        (source / "home/.themes/Night").mkdir(parents=True)
        (source / "home/.themes/Night/index.theme").write_text("gtk theme", encoding="utf-8")
        (source / "home/.local/share/fonts").mkdir(parents=True)
        (source / "home/.local/share/fonts/custom.ttf").write_bytes(b"font")
        (source / ".gtkrc-2.0").write_text("gtk theme setting", encoding="utf-8")
        (source / ".nanorc").write_text("set tabsize 4\n", encoding="utf-8")
        (source / "wallpapers").mkdir()
        (source / "wallpapers/my-wallpaper.png").write_bytes(b"image")
        (source / "wallpapers/alternate.png").write_bytes(b"alternate")
        switcher.THEMES.mkdir(parents=True)
        (switcher.THEMES / "wallpaper.png").write_bytes(b"local wallpaper" * 100)

        switcher.add_theme("sample", str(source))

        self.assertEqual(
            (switcher.THEMES / "sample/home/.config/hypr/hyprland.conf").read_text(),
            "hypr config",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/home/.config/waybar/style.css").read_text(),
            "bar style",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/home/.themes/Night/index.theme").read_text(),
            "gtk theme",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/home/.local/share/fonts/custom.ttf").read_bytes(),
            b"font",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/home/.gtkrc-2.0").read_text(),
            "gtk theme setting",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/home/.nanorc").read_text(),
            "set tabsize 4\n",
        )
        manifest = json.loads((switcher.THEMES / "sample/theme.json").read_text())
        self.assertTrue(manifest["wallpaper"].endswith("alternate.png"))
        self.assertEqual(
            (switcher.THEMES / "sample" / manifest["wallpaper"]).read_bytes(),
            b"alternate",
        )
        self.assertEqual(
            (switcher.THEMES / "sample/assets/wallpapers/my-wallpaper.png").read_bytes(),
            b"image",
        )
        self.assertNotIn(".config/mozilla", manifest["paths"])
        self.assertFalse((switcher.HOME / ".config/hypr").exists())

    def test_change_history_restores_the_version_before_the_selected_change(self):
        source = self.root / "history-rice"
        config = source / ".config/rofi/config.rasi"
        config.parent.mkdir(parents=True)
        config.write_text("original rofi config", encoding="utf-8")
        switcher.add_theme("history-rice", str(source), rewrite_paths=False)

        profile_config = (
            switcher.THEMES / "history-rice/home/.config/rofi/config.rasi"
        )
        profile_config.write_text("first rofi change", encoding="utf-8")
        first_change = switcher.collect_profile_changes("history-rice")[0]
        profile_config.write_text("second rofi change", encoding="utf-8")
        changes = switcher.collect_profile_changes("history-rice")
        second_change = changes[-1]

        switcher.restore_profile_change("history-rice", second_change["id"])
        self.assertEqual(profile_config.read_text(encoding="utf-8"), "first rofi change")
        switcher.restore_profile_change("history-rice", first_change["id"])
        self.assertEqual(profile_config.read_text(encoding="utf-8"), "original rofi config")

    def test_inactive_theme_history_restores_without_changing_the_active_rice(self):
        active_source = self.root / "active-source"
        active_config = active_source / ".config/rofi/config.rasi"
        active_config.parent.mkdir(parents=True)
        active_config.write_text("active theme", encoding="utf-8")
        other_source = self.root / "other-source"
        other_config = other_source / ".config/rofi/config.rasi"
        other_config.parent.mkdir(parents=True)
        other_config.write_text("other theme original", encoding="utf-8")

        switcher.add_theme("active", str(active_source), rewrite_paths=False)
        switcher.add_theme("other", str(other_source), rewrite_paths=False)
        with patch.object(
            switcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ):
            switcher.use_theme("active")
        (switcher.THEMES / "other/home/.config/rofi/config.rasi").write_text(
            "other theme modified", encoding="utf-8"
        )
        change = switcher.collect_profile_changes("other")[0]

        switcher.restore_profile_change("other", change["id"])

        self.assertEqual(
            (switcher.HOME / ".config/rofi/config.rasi").read_text(encoding="utf-8"),
            "active theme",
        )
        self.assertEqual(
            (switcher.THEMES / "other/home/.config/rofi/config.rasi").read_text(
                encoding="utf-8"
            ),
            "other theme original",
        )

    def test_reset_command_restores_only_the_requested_change(self):
        source = self.root / "cli-history"
        config = source / ".config/rofi/config.rasi"
        style = source / ".config/rofi/style.rasi"
        config.parent.mkdir(parents=True)
        config.write_text("original config", encoding="utf-8")
        style.write_text("original style", encoding="utf-8")
        switcher.add_theme("cli-history", str(source), rewrite_paths=False)

        profile = switcher.THEMES / "cli-history/home/.config/rofi"
        (profile / "config.rasi").write_text("changed config", encoding="utf-8")
        change = switcher.collect_profile_changes("cli-history")[0]
        (profile / "style.rasi").write_text("changed style", encoding="utf-8")
        switcher.collect_profile_changes("cli-history")

        switcher.main(["reset", "cli-history", "--change", change["id"]])

        self.assertEqual((profile / "config.rasi").read_text(), "original config")
        self.assertEqual((profile / "style.rasi").read_text(), "changed style")

    def test_rice_picker_opens_change_history_for_the_selected_profile(self):
        class Screen:
            def __init__(self):
                self.keys = [ord("r"), ord("q")]

            def getmaxyx(self):
                return (24, 80)

            def keypad(self, _enabled):
                pass

            def nodelay(self, _enabled):
                pass

            def erase(self):
                pass

            def addnstr(self, *_args):
                pass

            def refresh(self):
                pass

            def getch(self):
                return self.keys.pop(0)

        profile = self.root / "picker-rice"
        config = profile / ".config/rofi/config.rasi"
        config.parent.mkdir(parents=True)
        config.write_text("rofi", encoding="utf-8")
        switcher.add_theme("picker-rice", str(profile), rewrite_paths=False)
        item = switcher.list_profiles()[0]

        with patch.object(switcher, "_picker_colors", return_value={}), \
                patch.object(switcher, "_kitty_graphics_supported", return_value=False):
            selection = switcher.terminal_picker(Screen(), [item])

        self.assertEqual(selection, ("reset", "picker-rice"))

    def test_history_can_track_an_explicit_rice_runtime_setting(self):
        source = self.root / "tracked-state"
        config = source / "home/.config/rofi/config.rasi"
        config.parent.mkdir(parents=True)
        config.write_text("rofi config", encoding="utf-8")
        (source / "theme.json").write_text(json.dumps({
            "format": 2,
            "id": "tracked-state",
            "paths": [".config/rofi"],
            "tracked_paths": [".local/state/hakuspace/rofi-theme.rasi"],
        }), encoding="utf-8")
        state = switcher.HOME / ".local/state/hakuspace/rofi-theme.rasi"
        state.parent.mkdir(parents=True)
        state.write_text('@theme "television"\n', encoding="utf-8")
        switcher.add_theme("tracked-state", str(source), rewrite_paths=False)

        state.write_text('@theme "legacy"\n', encoding="utf-8")
        change = switcher.collect_profile_changes("tracked-state")[0]
        switcher.restore_profile_change("tracked-state", change["id"])

        self.assertEqual(state.read_text(), '@theme "television"\n')

    def test_import_rewrites_only_small_utf8_config_files(self):
        source = self.root / "source"
        hypr = source / "hypr"
        hypr.mkdir(parents=True)
        config = hypr / "hyprland.conf"
        config.write_text(
            "source = /home/another-user/.config/hypr/extra.conf\n",
            encoding="utf-8",
        )
        binary = hypr / "binary.conf"
        binary.write_bytes(b"/home/another-user/\x00binary")
        large = hypr / "large.conf"
        large.write_text(
            "/home/another-user/" + "x" * switcher.MAX_CONFIG_TEXT_BYTES,
            encoding="utf-8",
        )
        switcher.THEMES.mkdir()

        switcher.cmd_import(SimpleNamespace(
            name="rewrite",
            source=str(source),
            rewrite_paths=True,
        ))

        imported = switcher.THEMES / "rewrite/home/.config/hypr"
        self.assertIn(str(switcher.HOME), (imported / config.name).read_text())
        self.assertEqual((imported / binary.name).read_bytes(), binary.read_bytes())
        self.assertEqual((imported / large.name).read_text(), large.read_text())
        self.assertIn("/home/another-user/", config.read_text())

    def test_add_shallow_clones_a_file_url_and_imports_requested_subdirectory(self):
        repository = self.root / "repository"
        rice_source = repository / "rice-files"
        (rice_source / "hypr").mkdir(parents=True)
        (rice_source / "hypr/hyprland.conf").write_text(
            "exec-once = waybar\n", encoding="utf-8"
        )
        (rice_source / "bin").mkdir()
        (rice_source / "bin/launch-rice").write_text(
            "#!/bin/sh\n", encoding="utf-8"
        )
        (rice_source / "install.sh").write_text(
            f"touch {self.root / 'install-ran'}\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=repository, check=True)
        subprocess.run(["git", "config", "user.name", "Rice Test"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.email", "rice-test@example.invalid"],
            cwd=repository,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "rice"], cwd=repository, check=True)
        switcher.THEMES.mkdir()

        switcher.add_theme(
            "git-rice",
            repository.as_uri(),
            directory="rice-files",
            branch="main",
            rewrite_paths=False,
        )

        imported = switcher.THEMES / "git-rice/home/.config/hypr/hyprland.conf"
        self.assertEqual(imported.read_text(), "exec-once = waybar\n")
        self.assertTrue(
            (switcher.THEMES / "git-rice/home/.local/bin/launch-rice").is_file()
        )
        self.assertEqual(
            json.loads((switcher.THEMES / "git-rice/theme.json").read_text())[
                "extra_paths"
            ],
            [".local/bin"],
        )
        self.assertFalse((self.root / "install-ran").exists())

    def test_theme_switch_applies_config_fonts_icons_gtk_and_wallpaper_together(self):
        paths = [
            ".config/waybar",
            ".themes",
            ".icons",
            ".local/share/fonts",
            ".Xresources",
        ]
        files = {
            ".config/waybar/style.css": "bar",
            ".themes/Night/index.theme": "gtk",
            ".icons/Night/index.theme": "icons",
            ".local/share/fonts/custom.ttf": "font",
            ".Xresources": "terminal",
        }
        self.create_profile("complete", files, paths)
        theme_dir = switcher.THEMES / "complete"
        (theme_dir / "assets").mkdir()
        (theme_dir / "assets/wallpaper.png").write_bytes(b"image")
        manifest_path = theme_dir / "theme.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["settings"] = {
            "gtk_theme": "Night",
            "icon_theme": "Night",
            "cursor_theme": "Night",
            "color_scheme": "prefer-dark",
        }
        manifest["wallpaper"] = "assets/wallpaper.png"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        applied_settings = []
        applied_wallpapers = []
        switcher.apply_settings = lambda settings: applied_settings.append(settings)
        switcher.apply_wallpaper = lambda image: applied_wallpapers.append(image)

        switcher.use_theme("complete")

        for relative in paths:
            self.assertTrue(switcher.HOME.joinpath(relative).is_symlink(), relative)
        self.assertEqual(applied_settings[-1]["gtk_theme"], "Night")
        self.assertEqual(applied_settings[-1]["icon_theme"], "Night")
        self.assertEqual(applied_settings[-1]["cursor_theme"], "Night")
        self.assertEqual(applied_wallpapers[-1], theme_dir / "assets/wallpaper.png")

    def test_preview_palette_is_read_from_profile_configs(self):
        profile = self.root / "profile"
        kitty = profile / "home/.config/kitty"
        kitty.mkdir(parents=True)
        (kitty / "kitty.conf").write_text(
            "background #101010\ncolor1 #aa0000\n",
            encoding="utf-8",
        )
        (kitty / "theme-colors.conf").write_text(
            "background #202020\ncolor1 #bb3300\n",
            encoding="utf-8",
        )

        palette = switcher.profile_preview_palette(profile)

        self.assertEqual(palette["background"], "#202020")
        self.assertEqual(palette["accent"], "#bb3300")
        self.assertEqual(palette["surface"], palette["color0"])
        self.assertEqual(palette["swatches"][0], "#bb3300")

    def test_preview_prefers_the_quickshell_bar_colors_when_present(self):
        colors = (
            self.root
            / "profile/home/.config/rumda/common/quickshell/dark/config/Colors.qml"
        )
        colors.parent.mkdir(parents=True)
        colors.write_text(
            'property color backgroundColor: "#302820"\n'
            'property color accentColor: "#d18b55"\n',
            encoding="utf-8",
        )

        palette = switcher.profile_preview_palette(self.root / "profile")

        self.assertEqual(palette["background"], "#302820")
        self.assertEqual(palette["accent"], "#d18b55")

    def test_terminal_picker_selection_wraps_with_arrow_keys(self):
        self.assertEqual(
            switcher.move_selection(0, switcher.curses.KEY_UP, 3),
            2,
        )
        self.assertEqual(
            switcher.move_selection(2, switcher.curses.KEY_DOWN, 3),
            0,
        )
        self.assertEqual(
            switcher.move_selection(1, ord("x"), 3),
            1,
        )

    def test_terminal_picker_shows_a_styled_preview_and_applies_selection(self):
        class Screen:
            def __init__(self):
                self.keys = [switcher.curses.KEY_DOWN, 10]
                self.output = []

            def keypad(self, _enabled):
                pass

            def nodelay(self, _enabled):
                pass

            def erase(self):
                pass

            def getmaxyx(self):
                return (24, 100)

            def addnstr(self, _y, _x, text, _limit, _attr):
                self.output.append(text)

            def refresh(self):
                pass

            def getch(self):
                return self.keys.pop(0)

        items = [
            {"id": "one", "name": "First", "description": "First look", "paths": [".config/kitty"]},
            {"id": "two", "name": "Second", "description": "Second look", "paths": [".config/rofi"]},
        ]
        palette = {
            "background": "#111111",
            "accent": "#aa3366",
            "color0": "#111111",
            "surface": "#111111",
            "swatches": ["#aa3366"],
        }
        screen = Screen()
        with patch.object(switcher, "profile_preview_palette", return_value=palette), \
                patch.object(switcher, "_picker_colors", return_value={}), \
                patch.object(switcher, "_kitty_graphics_supported", return_value=False):
            selected = switcher.terminal_picker(screen, items)

        self.assertEqual(selected, "two")
        rendered = " ".join(screen.output)
        self.assertIn("RICE VAULT", rendered)
        self.assertIn("◈", rendered)
        self.assertIn("PREVIEW", rendered)
        self.assertIn("#aa3366", rendered)
        self.assertIn("Second look", rendered)

    def test_kitty_logo_uses_terminal_graphics_protocol(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "1"}), \
                patch.object(switcher.sys, "stdout", output):
            layout = switcher._render_kitty_logo(100)
            switcher._delete_kitty_logo()

        self.assertEqual(layout[0], 100)
        self.assertIn("\x1b_Ga=T", output.getvalue())
        self.assertIn("\x1b_Ga=d,d=i", output.getvalue())


if __name__ == "__main__":
    unittest.main()
