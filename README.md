# Theme Switch

<p align="center">
  <img src="theme-assets/theme-logo.png" alt="Rice — complete desktop profiles" width="100%">
</p>

**A safer way to switch complete Hyprland desktop profiles.**

Theme Switch is a Python command-line tool for managing Hyprland Rice profiles. A profile can bundle compositor and application configuration, GTK and icon settings, wallpapers, and other supported appearance files into one reversible switch.

> **Profiles are intentionally not included in this repository.** Keep profile data outside the source tree, in `~/.local/share/dotfile-themes` by default.

## Features

- Switch between installed Rice profiles, or use the interactive picker.
- Preview a switch and run health checks before or after applying a profile.
- Import profiles from a local directory or a Git repository.
- Keep backups and selectively restore individual changes.
- Preserve user-managed settings such as selected Hyprland and Kitty configuration.
- Inspect errors and environment readiness with `theme doctor`.

## Requirements

- Python 3.10 or newer; the CLI uses only the Python standard library.
- Hyprland and the programs required by the profile you want to apply.

## Install

Install the latest version from GitHub and link the `theme` command into `~/.local/bin`:

```sh
mkdir -p ~/.local/src ~/.local/bin &&
git clone https://github.com/abdullah4xx/theme-switch.git ~/.local/src/theme-switch &&
ln -sfn ~/.local/src/theme-switch/theme-switcher ~/.local/bin/theme
```

If `~/.local/bin` is not already on your `PATH`, add it in your shell configuration:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

## Quick start

```sh
theme list                 # Show installed profiles
theme status               # Show the active profile
theme doctor               # Check dependencies and profile state
theme -add                 # Inspect and install a compatible GitHub profile
theme preview hakuspace    # Preview a profile switch
theme use hakuspace        # Apply a profile
theme undo                 # Return to the previous profile
theme select               # Open the interactive picker
```

`theme -add` asks for a public GitHub repository URL, checks its profile files and required programs, and explains any incompatibility before making changes. Non-portable repository symlinks are listed and skipped. Detected installer scripts and lifecycle commands are reported but never run, and dependencies are checked rather than installed automatically. It asks for `y` before adding a compatible profile and does not switch the active desktop; use `theme use <profile>` when you are ready to apply it.

To add a profile from a local directory or a Git repository:

```sh
theme import my-rice /path/to/rice
theme add upstream-rice https://github.com/example/rice.git
```

Use `theme --help` and `theme <command> --help` for the complete command reference.

## Profile storage

The source code and installed profiles are kept separate:

| Purpose | Default path |
| --- | --- |
| Installed profiles | `~/.local/share/dotfile-themes/` |
| Backups and active state | `~/.local/state/dotfile-themes/` |

Override these locations with `DOTFILES_THEME_ROOT` and `DOTFILES_THEME_STATE`. Each profile is a directory containing a `theme.json` manifest and the files managed by that profile. For example:

```text
~/.local/share/dotfile-themes/
└── my-rice/
    ├── theme.json
    └── home/
        └── .config/
            └── hypr/
                └── hyprland.conf
```

The GitHub repository contains the switcher, tests, and its small application assets—not users' profile collections or personal configuration.

## Development

Run the test suite with Python's built-in unittest runner:

```sh
python3 -m unittest discover -s tests
```

The repository also includes `scripts/hyprlauncher`, a small dispatch helper for selecting the launcher associated with the active profile.

## Error reporting

Operational errors are reported with the `RICE-001` prefix to make them easy to identify in terminal output and logs.
