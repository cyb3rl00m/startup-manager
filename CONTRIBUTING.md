# Contributing

Thanks for wanting to help! Contributions of any size are welcome — from a typo fix to support for a
new desktop.

## Easiest way to help: test it on your system

Startup Manager is built on Ubuntu 26.04 with GNOME. If you use another distribution or desktop
(KDE Plasma, Cinnamon, Xfce, COSMIC, …), [open an issue](../../issues/new?template=bug_report.yml)
and tell us whether your startup entries and commands ran at login.

## Running from source

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1   # Ubuntu/Debian
git clone https://github.com/cyb3rl00m/startup-manager.git
cd startup-manager
python3 startup-manager
```

## Tests

```bash
python3 -m unittest discover tests
```

The tests run inside a temporary home folder, so they never touch your real startup entries. They
cover reading and writing `.desktop` files, overriding system entries, finding installed apps, and
creating, running and logging custom commands. Please make sure they pass before opening a pull request.

## Project layout

| Path | What it does |
|---|---|
| `src/startup_manager/core.py` | Everything that touches the system: listing, adding, turning off, removing entries; custom commands. **No GTK.** |
| `src/startup_manager/desktopfile.py` | Reads and writes `.desktop` files without changing their layout |
| `src/startup_manager/window.py` | Main window: Apps and Commands tabs |
| `src/startup_manager/dialogs.py` | Add App, program, command and output dialogs |
| `src/startup_manager/main.py` | Application setup, `--version`, missing-dependency message |
| `packaging/build-deb.sh` | Builds the `.deb` |

## Rules for code that changes startup entries

`core.py` decides what gets written to your autostart folder. Changes there must:

1. never write outside the user's own folders (`~/.config/autostart`, `~/.local/share/startup-manager`,
   `~/.local/state/startup-manager`),
2. never edit files in `/etc/xdg/autostart` — override them with a per-user copy instead,
3. come with a test in `tests/test_core.py`.

## Building the .deb

```bash
bash packaging/build-deb.sh       # → dist/startup-manager_<version>_all.deb
```

The version comes from `src/startup_manager/__init__.py`.

Publishing a GitHub release builds the `.deb` and attaches it to the release automatically.
