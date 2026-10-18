# Changelog

## 1.0.0 — 2026-10-18

First release.

- **Apps tab:** every startup entry with an on/off switch, grouped into *Your Startup Apps*,
  *Added by Installed Software* and (optional) *System Services*.
- Add installed apps (APT, Snap, Flatpak, local) from a searchable list, or any program by its command.
- Edit name, command, description and start delay. A warning appears when a program no longer exists.
- System entries are turned off with a per-user copy, never by editing `/etc/xdg/autostart`.
  **Restore Default** removes the copy again.
- Asks before turning off a system service.
- **Commands tab:** run your own bash commands at login, with a live `bash -n` syntax check, an
  optional delay, *Wait for Network*, **Run Now** and **View Output** (logs capped at 256 KB).
- Typing a shell command (pipes, `~`, `&&`, variables) as a program offers to make it a command instead.
- Undo for adding, removing and restoring entries.
- Refreshes automatically when entries change outside the app.
- Search, keyboard shortcuts (Ctrl+N, Ctrl+F, F5) and a narrow-window layout.
- `.deb` package (`packaging/build-deb.sh`) and `install.sh` for any distribution.
