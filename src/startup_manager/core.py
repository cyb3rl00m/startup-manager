"""Everything Startup Manager does to the system, without any GTK.

How login autostart works on Ubuntu (and every XDG desktop):

* Session-wide entries live in /etc/xdg/autostart (more generally, in
  ``$XDG_CONFIG_DIRS/autostart``). Only root can change them.
* Per-user entries live in ~/.config/autostart. A user file with the same
  file name *overrides* the system one, which is how a normal user can turn a
  system entry off: copy it and add ``Hidden=true`` /
  ``X-GNOME-Autostart-enabled=false``.

Custom commands are stored as small bash scripts in
~/.local/share/startup-manager/commands, each launched by its own ordinary
autostart entry. They keep working even if this app is uninstalled, and every
run appends its output to ~/.local/state/startup-manager/logs.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

from .desktopfile import DesktopFile, quote_exec_arg, split_exec, strip_field_codes

APP_TAG = "startup-manager"
KEY_COMMAND = "X-Startup-Manager-Command"
KEY_OVERRIDE = "X-Startup-Manager-Override"  # "toggle" or "edit"
KEY_SOURCE = "X-Startup-Manager-Source"
KEY_CMD_DELAY = "X-Startup-Manager-Delay"
KEY_CMD_WAIT_NET = "X-Startup-Manager-WaitNetwork"
KEY_GNOME_ENABLED = "X-GNOME-Autostart-enabled"
KEY_GNOME_DELAY = "X-GNOME-Autostart-Delay"

BEGIN_MARK = "# ----- BEGIN USER COMMAND -----"
END_MARK = "# ----- END USER COMMAND -----"
LOG_LIMIT_BYTES = 256 * 1024
_COMMAND_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------
def _home() -> str:
    return os.path.expanduser("~")


def _xdg(var: str, fallback: str) -> str:
    val = os.environ.get(var, "").strip()
    return val if val and os.path.isabs(val) else os.path.join(_home(), fallback)


def user_autostart_dir() -> str:
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "autostart")


def system_autostart_dirs() -> list[str]:
    raw = os.environ.get("XDG_CONFIG_DIRS", "").strip() or "/etc/xdg"
    dirs = [os.path.join(d, "autostart") for d in raw.split(":") if d]
    return list(dict.fromkeys(dirs))


def commands_dir() -> str:
    return os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP_TAG, "commands")


def logs_dir() -> str:
    return os.path.join(_xdg("XDG_STATE_HOME", ".local/state"), APP_TAG, "logs")


def data_dirs() -> list[str]:
    dirs = [_xdg("XDG_DATA_HOME", ".local/share")]
    dirs.append(os.path.join(_home(), ".local/share/flatpak/exports/share"))
    raw = os.environ.get("XDG_DATA_DIRS", "").strip() or "/usr/local/share:/usr/share"
    dirs.extend(d for d in raw.split(":") if d)
    dirs.extend(["/var/lib/flatpak/exports/share", "/var/lib/snapd/desktop"])
    return list(dict.fromkeys(os.path.normpath(d) for d in dirs))


def current_desktops() -> list[str]:
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return [d.lower() for d in raw.split(":") if d]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def applies_to_desktop(df: DesktopFile) -> bool:
    desktops = current_desktops()
    if not desktops:
        return True
    only = [d.lower() for d in df.get_list("OnlyShowIn")]
    if only and not set(only) & set(desktops):
        return False
    hide = [d.lower() for d in df.get_list("NotShowIn")]
    return not set(hide) & set(desktops)


def _program_exists(prog: str) -> bool:
    if not prog:
        return False
    if "/" in prog:
        return os.path.isfile(prog) and os.access(prog, os.X_OK)
    return shutil.which(prog) is not None


def tryexec_ok(df: DesktopFile) -> bool:
    tryexec = df.get("TryExec")
    return True if not tryexec else _program_exists(tryexec)


def command_program(command: str) -> str | None:
    """Return the program a command line would start (skipping `env VAR=x`)."""
    try:
        args = split_exec(command)
    except Exception:
        return None
    if args and os.path.basename(args[0]) == "env":
        args = args[1:]
        while args and (args[0].startswith("-") or "=" in args[0]):
            args = args[1:]
    return args[0] if args else None


def command_exists(command: str) -> bool:
    prog = command_program(command)
    return bool(prog) and _program_exists(prog)


_SHELL_RE = re.compile(r"[|;&<>`]|\$\(|\$\{|\$[A-Za-z_]|(^|\s)~|\*")


def looks_like_shell(command: str) -> bool:
    """True if a command uses shell syntax that an Exec= line cannot run."""
    return bool(_SHELL_RE.search(command))


def check_bash_syntax(body: str) -> tuple[bool, str]:
    """Run `bash -n` on a command body. Returns (ok, message)."""
    bash = shutil.which("bash") or "/bin/bash"
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as fh:
        fh.write(body + "\n")
        tmp = fh.name
    try:
        proc = subprocess.run([bash, "-n", tmp], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Could not run bash: {exc}"
    finally:
        os.unlink(tmp)
    if proc.returncode == 0:
        return True, ""
    msg = proc.stderr.replace(tmp + ": ", "").strip()
    return False, msg or "bash reported a syntax error"


def slugify(text: str, limit: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "entry"


def _unique_filename(base: str) -> str:
    taken_dirs = [user_autostart_dir(), *system_autostart_dirs()]
    candidate = f"{base}.desktop"
    n = 2
    while any(os.path.exists(os.path.join(d, candidate)) for d in taken_dirs):
        candidate = f"{base}-{n}.desktop"
        n += 1
    return candidate


def _is_enabled(df: DesktopFile) -> bool:
    return not df.get_bool("Hidden") and df.get_bool(KEY_GNOME_ENABLED, True)


def _apply_enabled(df: DesktopFile, enabled: bool) -> None:
    if enabled:
        df.remove("Hidden")
        df.set_bool(KEY_GNOME_ENABLED, True)
    else:
        df.set_bool("Hidden", True)
        df.set_bool(KEY_GNOME_ENABLED, False)


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Autostart entries
# --------------------------------------------------------------------------
@dataclass
class AutostartEntry:
    filename: str
    user_path: str | None
    system_path: str | None
    df: DesktopFile  # the file that is actually in effect
    system_df: DesktopFile | None = None

    def _field(self, key: str, localized: bool = True) -> str | None:
        for src in (self.df, self.system_df):
            if src is None:
                continue
            val = src.get_localized(key) if localized else src.get(key)
            if val:
                return val
        return None

    # identity / origin
    @property
    def origin(self) -> str:
        """'user', 'system' or 'override' (user copy of a system entry)."""
        if self.user_path and self.system_path:
            return "override"
        return "user" if self.user_path else "system"

    @property
    def command_id(self) -> str | None:
        if not self.user_path:
            return None
        cid = self.df.get(KEY_COMMAND)
        # Only IDs this app generates are accepted, so a hand-made entry can't
        # point Run Now / Remove at a file outside the commands folder.
        return cid if cid and _COMMAND_ID_RE.fullmatch(cid) else None

    @property
    def kind(self) -> str:
        """'command', 'app' (shown by default) or 'service' (background parts of the desktop)."""
        if self.command_id:
            return "command"
        if self.origin == "user":
            return "app"
        df = self.system_df or self.df
        if (
            df.get_bool("NoDisplay")
            or df.has("X-GNOME-Autostart-Phase")
            or not applies_to_desktop(df)
            or not tryexec_ok(df)
        ):
            return "service"
        return "app"

    # display
    @property
    def name(self) -> str:
        return self._field("Name") or self.filename.removesuffix(".desktop")

    @property
    def comment(self) -> str:
        return self._field("Comment") or self._field("GenericName") or ""

    @property
    def icon(self) -> str | None:
        return self._field("Icon", localized=False)

    @property
    def exec_line(self) -> str:
        return self._field("Exec", localized=False) or ""

    @property
    def command(self) -> str:
        return strip_field_codes(self.exec_line)

    @property
    def enabled(self) -> bool:
        return _is_enabled(self.df)

    @property
    def delay(self) -> int:
        key = KEY_CMD_DELAY if self.command_id else KEY_GNOME_DELAY
        try:
            return max(0, int(float(self.df.get(key) or 0)))
        except ValueError:
            return 0

    @property
    def condition(self) -> str | None:
        return self._field("AutostartCondition", localized=False)

    @property
    def program_missing(self) -> bool:
        if self.command_id or self.df.get_bool("DBusActivatable"):
            return False
        return bool(self.command) and not command_exists(self.command)

    @property
    def can_remove(self) -> bool:
        return self.user_path is not None

    @property
    def path(self) -> str:
        return self.user_path or self.system_path or ""

    # commands
    @property
    def script_path(self) -> str | None:
        cid = self.command_id
        return os.path.join(commands_dir(), f"{cid}.sh") if cid else None

    @property
    def log_path(self) -> str | None:
        cid = self.command_id
        return os.path.join(logs_dir(), f"{cid}.log") if cid else None

    @property
    def wait_network(self) -> bool:
        return self.df.get_bool(KEY_CMD_WAIT_NET)


def list_entries() -> list[AutostartEntry]:
    system: dict[str, str] = {}
    for d in system_autostart_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in names:
            if fn.endswith(".desktop") and fn not in system:
                system[fn] = os.path.join(d, fn)

    user: dict[str, str] = {}
    udir = user_autostart_dir()
    try:
        for fn in sorted(os.listdir(udir)):
            if fn.endswith(".desktop") and os.path.isfile(os.path.join(udir, fn)):
                user[fn] = os.path.join(udir, fn)
    except OSError:
        pass

    entries: list[AutostartEntry] = []
    for fn in sorted(set(system) | set(user)):
        try:
            sys_df = DesktopFile.load(system[fn]) if fn in system else None
            usr_df = DesktopFile.load(user[fn]) if fn in user else None
        except OSError:
            continue
        effective = usr_df or sys_df
        if effective is None:
            continue
        entries.append(AutostartEntry(fn, user.get(fn), system.get(fn), effective, sys_df))
    entries.sort(key=lambda e: e.name.casefold())
    return entries


def get_entry(filename: str) -> AutostartEntry | None:
    return next((e for e in list_entries() if e.filename == filename), None)


def set_enabled(entry: AutostartEntry, enabled: bool) -> None:
    if entry.user_path:
        df = DesktopFile.load(entry.user_path)
        # A pure on/off override that matches the system default again is
        # just deleted, so future package updates to the entry apply.
        if (
            df.get(KEY_OVERRIDE) == "toggle"
            and entry.system_df is not None
            and _is_enabled(entry.system_df) == enabled
        ):
            os.remove(entry.user_path)
            return
        _apply_enabled(df, enabled)
        df.save()
        return
    if entry.system_path is None:
        return
    df = DesktopFile(_read(entry.system_path))
    df.set(KEY_OVERRIDE, "toggle")
    _apply_enabled(df, enabled)
    df.save(os.path.join(user_autostart_dir(), entry.filename))


@dataclass
class UndoInfo:
    """File contents needed to undo a removal ({path: text})."""
    files: dict[str, str] = field(default_factory=dict)
    label: str = ""


def remove_entry(entry: AutostartEntry) -> UndoInfo:
    """Delete a user entry (and a command's script). System entries can't be removed."""
    if not entry.user_path:
        raise PermissionError("System entries can only be turned off, not removed.")
    undo = UndoInfo(label=entry.name)
    paths = [entry.user_path]
    if entry.script_path:
        paths.append(entry.script_path)
    for p in paths:
        if os.path.exists(p):
            undo.files[p] = _read(p)
    for p in paths:
        if os.path.exists(p):
            os.remove(p)
    return undo


def restore(undo: UndoInfo) -> None:
    for path, text in undo.files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if path.endswith(".sh"):
            os.chmod(path, 0o700)


def restore_default(entry: AutostartEntry) -> UndoInfo:
    """Drop the user's copy of a system entry, going back to the system version."""
    if entry.origin != "override":
        raise ValueError("This entry has no system default to go back to.")
    return remove_entry(entry)


def update_entry(entry: AutostartEntry, name: str, command: str, comment: str, delay: int) -> None:
    """Edit name/command/comment/delay of an app entry (system ones get a user copy)."""
    if entry.user_path:
        df = DesktopFile.load(entry.user_path)
        target = entry.user_path
    else:
        df = DesktopFile(_read(entry.system_path))
        target = os.path.join(user_autostart_dir(), entry.filename)
    if entry.system_path:
        df.set(KEY_OVERRIDE, "edit")

    name, command, comment = name.strip(), command.strip(), comment.strip()
    if name != entry.name:
        df.remove("Name", with_translations=True)
        df.set("Name", name)
    if comment != entry.comment:
        df.remove("Comment", with_translations=True)
        if comment:
            df.set("Comment", comment)
    if command != entry.command:
        df.set("Exec", command)
        df.remove("TryExec")
        df.remove("DBusActivatable")
    if delay > 0:
        df.set(KEY_GNOME_DELAY, str(int(delay)))
    else:
        df.remove(KEY_GNOME_DELAY)
    df.save(target)


# --------------------------------------------------------------------------
# Installed applications (for "Add App")
# --------------------------------------------------------------------------
@dataclass
class InstalledApp:
    desktop_id: str
    path: str
    name: str
    comment: str
    icon: str | None
    command: str

    @property
    def source(self) -> str:
        p = self.path
        if "/snapd/" in p or p.startswith("/snap/"):
            return "Snap"
        if "flatpak" in p:
            return "Flatpak"
        if p.startswith(_home()):
            return "Local"
        return "System"


def list_installed_apps() -> list[InstalledApp]:
    seen: set[str] = set()
    apps: list[InstalledApp] = []
    for base in data_dirs():
        appdir = os.path.join(base, "applications")
        if not os.path.isdir(appdir):
            continue
        for root, _dirs, files in os.walk(appdir):
            for fn in sorted(files):
                if not fn.endswith(".desktop"):
                    continue
                path = os.path.join(root, fn)
                desktop_id = os.path.relpath(path, appdir).replace(os.sep, "-")
                if desktop_id in seen:
                    continue
                seen.add(desktop_id)  # the first directory wins, even if hidden
                try:
                    df = DesktopFile.load(path)
                except OSError:
                    continue
                if (
                    df.get("Type") != "Application"
                    or df.get_bool("NoDisplay")
                    or df.get_bool("Hidden")
                    or not df.get("Exec")
                    or not applies_to_desktop(df)
                    or not tryexec_ok(df)
                ):
                    continue
                apps.append(
                    InstalledApp(
                        desktop_id=desktop_id,
                        path=path,
                        name=df.get_localized("Name") or desktop_id.removesuffix(".desktop"),
                        comment=df.get_localized("Comment") or df.get_localized("GenericName") or "",
                        icon=df.get("Icon"),
                        command=strip_field_codes(df.get("Exec") or ""),
                    )
                )
    apps.sort(key=lambda a: a.name.casefold())
    return apps


def add_app(app: InstalledApp, delay: int = 0) -> str:
    """Make an installed app start at login. Returns the autostart file path."""
    target = os.path.join(user_autostart_dir(), app.desktop_id)
    if os.path.exists(target):
        df = DesktopFile.load(target)
    else:
        df = DesktopFile.load(app.path)
        df.keep_only_main_group()
        df.remove("Actions")
        df.set(KEY_SOURCE, app.path)
    _apply_enabled(df, True)
    if delay > 0:
        df.set(KEY_GNOME_DELAY, str(int(delay)))
    df.save(target)
    return target


def add_custom_program(name: str, command: str, comment: str = "", delay: int = 0) -> str:
    df = DesktopFile("[Desktop Entry]\n")
    df.set("Type", "Application")
    df.set("Name", name.strip())
    if comment.strip():
        df.set("Comment", comment.strip())
    df.set("Exec", command.strip())
    df.set("Icon", "application-x-executable")
    df.set("Terminal", "false")
    _apply_enabled(df, True)
    if delay > 0:
        df.set(KEY_GNOME_DELAY, str(int(delay)))
    target = os.path.join(user_autostart_dir(), _unique_filename(slugify(name)))
    df.save(target)
    return target


# --------------------------------------------------------------------------
# Custom bash commands
# --------------------------------------------------------------------------
def build_script(command_id: str, name: str, body: str, delay: int, wait_network: bool) -> str:
    safe_name = " ".join(name.split())
    lines = [
        "#!/usr/bin/env bash",
        f"# Startup command: {safe_name}",
        "# Created by Startup Manager. Runs at login; output goes to the log below.",
        "# You can edit the part between the BEGIN/END markers by hand.",
        "",
        f'LOG_DIR="${{XDG_STATE_HOME:-$HOME/.local/state}}/{APP_TAG}/logs"',
        f'LOG="$LOG_DIR/{command_id}.log"',
        '(umask 077; mkdir -p "$LOG_DIR")',
        f'if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt {LOG_LIMIT_BYTES} ]; then mv -f "$LOG" "$LOG.old"; fi',
        '(umask 077; touch "$LOG")',
        'exec >>"$LOG" 2>&1',
        'echo "=== $(date "+%Y-%m-%d %H:%M:%S") started ==="',
        "trap 'rc=$?; echo \"=== $(date \"+%Y-%m-%d %H:%M:%S\") finished (exit code $rc) ===\"' EXIT",
    ]
    if delay > 0:
        lines.append(f'if [ -z "${{STARTUP_MANAGER_NOW:-}}" ]; then sleep {int(delay)}; fi')
    if wait_network:
        lines += [
            "if command -v nm-online >/dev/null 2>&1; then",
            '    nm-online -q -t 60 || echo "network still offline after 60 s, continuing anyway"',
            "fi",
        ]
    lines += ["", BEGIN_MARK, body.rstrip("\n"), END_MARK, ""]
    return "\n".join(lines)


def read_command_body(entry: AutostartEntry) -> str:
    path = entry.script_path
    if not path or not os.path.exists(path):
        return ""
    text = _read(path)
    start = text.find(BEGIN_MARK)
    end = text.rfind(END_MARK)
    if start != -1 and end > start:
        return text[start + len(BEGIN_MARK):end].strip("\n")
    # Edited by hand without markers: show everything after the shebang.
    return re.sub(r"\A#![^\n]*\n", "", text).strip("\n")


def _write_command(command_id: str, filename: str, name: str, body: str,
                   delay: int, wait_network: bool, enabled: bool,
                   existing: DesktopFile | None = None) -> str:
    script = os.path.join(commands_dir(), f"{command_id}.sh")
    os.makedirs(commands_dir(), mode=0o700, exist_ok=True)
    tmp = script + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(build_script(command_id, name, body, delay, wait_network))
    os.chmod(tmp, 0o700)
    os.replace(tmp, script)

    df = existing or DesktopFile("[Desktop Entry]\n")
    df.set("Type", "Application")
    df.remove("Name", with_translations=True)
    df.set("Name", " ".join(name.split()))
    df.set("Comment", "Custom startup command")
    df.set("Exec", f"bash {quote_exec_arg(script)}")
    df.set("Icon", "utilities-terminal")
    df.set("Terminal", "false")
    df.set(KEY_COMMAND, command_id)
    df.set(KEY_CMD_DELAY, str(max(0, int(delay))))
    df.set_bool(KEY_CMD_WAIT_NET, wait_network)
    _apply_enabled(df, enabled)
    target = os.path.join(user_autostart_dir(), filename)
    df.save(target)
    return target


def create_command(name: str, body: str, delay: int = 0, wait_network: bool = False,
                   enabled: bool = True) -> str:
    command_id = f"{slugify(name, 24)}-{secrets.token_hex(3)}"
    filename = f"{APP_TAG}-cmd-{command_id}.desktop"
    return _write_command(command_id, filename, name, body, delay, wait_network, enabled)


def update_command(entry: AutostartEntry, name: str, body: str, delay: int,
                   wait_network: bool) -> str:
    if not entry.command_id or not entry.user_path:
        raise ValueError("Not a custom command")
    return _write_command(entry.command_id, entry.filename, name, body, delay,
                          wait_network, entry.enabled, DesktopFile.load(entry.user_path))


def run_command_now(entry: AutostartEntry) -> subprocess.Popen:
    """Start a command's script right away (skipping its delay) for testing."""
    script = entry.script_path
    if not script or not os.path.exists(script):
        raise FileNotFoundError("The command's script is missing.")
    env = dict(os.environ, STARTUP_MANAGER_NOW="1")
    return subprocess.Popen(
        [shutil.which("bash") or "/bin/bash", script],
        env=env, cwd=_home(),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def read_log(entry: AutostartEntry, max_bytes: int = 200_000) -> str:
    path = entry.log_path
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = "…(older output trimmed)\n" + text.split("\n", 1)[-1]
    return text


def clear_log(entry: AutostartEntry) -> None:
    for path in (entry.log_path, (entry.log_path or "") + ".old"):
        if path and os.path.exists(path):
            os.remove(path)


def describe_command_for_shell(command: str) -> str:
    """Shell-quoted version of an Exec command, for copying into a terminal."""
    try:
        return shlex.join(split_exec(command))
    except Exception:
        return command
