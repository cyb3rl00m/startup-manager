"""Tests for the GTK-free core. Run with:  python3 -m unittest discover tests"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from startup_manager import core  # noqa: E402
from startup_manager.desktopfile import DesktopFile, quote_exec_arg, split_exec, strip_field_codes  # noqa: E402


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.home = os.path.join(root, "home")
        self.etc = os.path.join(root, "etc/xdg")
        self.share = os.path.join(root, "usr/share")
        os.makedirs(self.home)
        self._env = dict(os.environ)
        os.environ.update(
            HOME=self.home,
            XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
            XDG_DATA_HOME=os.path.join(self.home, ".local/share"),
            XDG_STATE_HOME=os.path.join(self.home, ".local/state"),
            XDG_CONFIG_DIRS=self.etc,
            XDG_DATA_DIRS=self.share,
            XDG_CURRENT_DESKTOP="ubuntu:GNOME",
            LANG="de_DE.UTF-8",
        )
        os.environ.pop("LANGUAGE", None)
        os.environ.pop("LC_ALL", None)
        os.environ.pop("LC_MESSAGES", None)
        self.user_dir = core.user_autostart_dir()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def sys_entry(self, fn, text):
        write(os.path.join(self.etc, "autostart", fn), text)


class DesktopFileTests(unittest.TestCase):
    def test_round_trip_keeps_layout(self):
        text = "# comment\n[Desktop Entry]\nName=A\nName[de]=B\n\n[Desktop Action new]\nExec=x\n"
        self.assertEqual(DesktopFile(text).to_text(), text)

    def test_localized_and_escapes(self):
        os.environ["LANGUAGE"] = "de_AT:en"
        try:
            df = DesktopFile("[Desktop Entry]\nName=Files\nName[de]=Dateien\nComment=a\\nb\n")
            self.assertEqual(df.get_localized("Name"), "Dateien")
            self.assertEqual(df.get("Comment"), "a\nb")
        finally:
            del os.environ["LANGUAGE"]

    def test_set_escapes_and_inserts_before_blank(self):
        df = DesktopFile("[Desktop Entry]\nName=x\n\n[Other]\nA=1\n")
        df.set("Comment", "line1\nline2")
        self.assertIn("Comment=line1\\nline2\n\n[Other]", df.to_text())

    def test_exec_quoting_round_trip(self):
        path = '/home/a b/$weird"file.sh'
        quoted = quote_exec_arg(path)
        df = DesktopFile("[Desktop Entry]\n")
        df.set("Exec", f"bash {quoted}")
        reread = DesktopFile(df.to_text())
        self.assertEqual(split_exec(reread.get("Exec")), ["bash", path])

    def test_strip_field_codes(self):
        self.assertEqual(strip_field_codes("firefox %u"), "firefox")
        self.assertEqual(strip_field_codes("app --x %F --y"), "app --x --y")
        self.assertEqual(strip_field_codes("echo 100%%"), "echo 100%")


class EntryTests(Sandbox):
    def test_classification_and_override(self):
        self.sys_entry("tracker.desktop", "[Desktop Entry]\nName=Tracker\nExec=true\nNoDisplay=true\n")
        self.sys_entry("kde.desktop", "[Desktop Entry]\nName=KDE thing\nExec=true\nOnlyShowIn=KDE;\n")
        self.sys_entry("update.desktop", "[Desktop Entry]\nName=Update Notifier\nName[de]=Aktualisierung\nExec=true\n")
        entries = {e.filename: e for e in core.list_entries()}
        self.assertEqual(entries["tracker.desktop"].kind, "service")
        self.assertEqual(entries["kde.desktop"].kind, "service")
        upd = entries["update.desktop"]
        self.assertEqual((upd.kind, upd.origin, upd.enabled, upd.name), ("app", "system", True, "Aktualisierung"))
        self.assertFalse(upd.can_remove)

        core.set_enabled(upd, False)
        upd = core.get_entry("update.desktop")
        self.assertEqual((upd.origin, upd.enabled), ("override", False))
        text = read(upd.user_path)
        self.assertIn("Hidden=true", text)
        self.assertIn("X-GNOME-Autostart-enabled=false", text)

        # Turning it back on deletes the pure toggle override.
        core.set_enabled(upd, True)
        upd = core.get_entry("update.desktop")
        self.assertEqual((upd.origin, upd.enabled), ("system", True))
        self.assertFalse(os.path.exists(os.path.join(self.user_dir, "update.desktop")))

        with self.assertRaises(PermissionError):
            core.remove_entry(upd)

    def test_edit_system_entry_then_restore_default(self):
        self.sys_entry("upd.desktop", "[Desktop Entry]\nName=Upd\nName[de]=Akt\nExec=true %u\nTryExec=true\n")
        e = core.get_entry("upd.desktop")
        core.update_entry(e, "My Upd", "sleep 1", "", 15)
        e = core.get_entry("upd.desktop")
        self.assertEqual((e.origin, e.name, e.command, e.delay), ("override", "My Upd", "sleep 1", 15))
        self.assertIsNone(e.df.get("TryExec"))
        core.set_enabled(e, False)
        core.set_enabled(core.get_entry("upd.desktop"), True)
        # An edited override is kept when re-enabled.
        self.assertEqual(core.get_entry("upd.desktop").origin, "override")
        core.restore_default(core.get_entry("upd.desktop"))
        self.assertEqual(core.get_entry("upd.desktop").name, "Akt")

    def test_unchanged_edit_keeps_exec_field_codes(self):
        write(os.path.join(self.user_dir, "a.desktop"), "[Desktop Entry]\nName=A\nExec=true %U\n")
        e = core.get_entry("a.desktop")
        core.update_entry(e, "A", e.command, "", 0)
        self.assertEqual(core.get_entry("a.desktop").exec_line, "true %U")

    def test_custom_program_remove_and_undo(self):
        path = core.add_custom_program("Sync Notes", "true --flag", "", 5)
        e = core.get_entry(os.path.basename(path))
        self.assertEqual((e.kind, e.origin, e.delay, e.enabled), ("app", "user", 5, True))
        self.assertFalse(e.program_missing)
        core.set_enabled(e, False)
        self.assertFalse(core.get_entry(e.filename).enabled)
        undo = core.remove_entry(core.get_entry(e.filename))
        self.assertIsNone(core.get_entry(e.filename))
        core.restore(undo)
        self.assertFalse(core.get_entry(e.filename).enabled)
        # Same name again gets a different file.
        self.assertNotEqual(core.add_custom_program("Sync Notes", "true"), path)

    def test_missing_program_detected(self):
        write(os.path.join(self.user_dir, "x.desktop"), "[Desktop Entry]\nName=X\nExec=/nope/missing-prog --a\n")
        self.assertTrue(core.get_entry("x.desktop").program_missing)

    def test_installed_apps_and_add(self):
        apps = os.path.join(self.share, "applications")
        write(os.path.join(apps, "org.example.Notes.desktop"),
              "[Desktop Entry]\nType=Application\nName=Notes\nExec=true %U\nActions=new;\n\n"
              "[Desktop Action new]\nName=New\nExec=true --new\n")
        write(os.path.join(apps, "hidden.desktop"), "[Desktop Entry]\nType=Application\nName=H\nExec=true\nNoDisplay=true\n")
        write(os.path.join(apps, "kde4", "konsole.desktop"), "[Desktop Entry]\nType=Application\nName=Konsole\nExec=true\n")
        write(os.path.join(apps, "gone.desktop"), "[Desktop Entry]\nType=Application\nName=Gone\nExec=x\nTryExec=/nope/x\n")
        # A user copy marked NoDisplay hides the system app.
        write(os.path.join(self.home, ".local/share/applications/konsole2.desktop"),
              "[Desktop Entry]\nType=Application\nName=K2\nExec=true\n")
        found = {a.desktop_id: a for a in core.list_installed_apps()}
        self.assertEqual(set(found), {"org.example.Notes.desktop", "kde4-konsole.desktop", "konsole2.desktop"})
        self.assertEqual(found["konsole2.desktop"].source, "Local")

        path = core.add_app(found["org.example.Notes.desktop"], delay=10)
        text = read(path)
        self.assertNotIn("Desktop Action", text)
        self.assertNotIn("Actions=", text)
        e = core.get_entry("org.example.Notes.desktop")
        self.assertEqual((e.enabled, e.delay, e.command), (True, 10, "true"))


class CommandTests(Sandbox):
    def test_syntax_check(self):
        self.assertEqual(core.check_bash_syntax("echo hi\nif true; then echo ok; fi"), (True, ""))
        ok, msg = core.check_bash_syntax("if true; then\necho x\n")
        self.assertFalse(ok)
        self.assertIn("syntax error", msg)
        self.assertNotIn("/tmp", msg)

    def test_looks_like_shell(self):
        for cmd in ("a | b", "a && b", "echo $HOME", "~/bin/x", "a > f", "x $(y)"):
            self.assertTrue(core.looks_like_shell(cmd), cmd)
        for cmd in ("firefox --new-window", "env FOO=1 app", "/usr/bin/app -x"):
            self.assertFalse(core.looks_like_shell(cmd), cmd)

    def test_command_lifecycle(self):
        body = 'echo "hello from $USER-test"\nmkdir -p "$HOME/made-by-startup"\n'
        path = core.create_command("Make folder", body, delay=30, wait_network=True)
        e = core.get_entry(os.path.basename(path))
        self.assertEqual((e.kind, e.delay, e.wait_network, e.enabled), ("command", 30, True, True))
        self.assertEqual(core.read_command_body(e), body.rstrip("\n"))
        self.assertTrue(os.access(e.script_path, os.X_OK))
        # The Exec line points at the script.
        self.assertEqual(split_exec(e.df.get("Exec")), ["bash", e.script_path])

        # "Run now" skips the 30 s delay and logs output.
        proc = core.run_command_now(e)
        self.assertEqual(proc.wait(timeout=90), 0)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "made-by-startup")))
        log = core.read_log(e)
        self.assertIn("hello from", log)
        self.assertIn("finished (exit code 0)", log)

        core.set_enabled(e, False)
        e = core.get_entry(e.filename)
        core.update_command(e, "Renamed", "exit 3", 0, False)
        e = core.get_entry(e.filename)
        self.assertEqual((e.name, e.delay, e.wait_network, e.enabled), ("Renamed", 0, False, False))
        script = read(e.script_path)
        self.assertNotIn("sleep", script)
        self.assertNotIn("nm-online", script)
        subprocess.run(["bash", "-n", e.script_path], check=True)
        self.assertEqual(core.run_command_now(e).wait(timeout=30), 3)
        self.assertIn("exit code 3", core.read_log(e))

        core.clear_log(e)
        self.assertEqual(core.read_log(e), "")
        undo = core.remove_entry(e)
        self.assertFalse(os.path.exists(e.script_path))
        core.restore(undo)
        self.assertTrue(os.access(e.script_path, os.X_OK))
        self.assertEqual(core.get_entry(e.filename).kind, "command")

    def test_logs_are_private_and_bad_ids_rejected(self):
        e = core.get_entry(os.path.basename(core.create_command("Private", "echo secret")))
        core.run_command_now(e).wait(timeout=30)
        self.assertEqual(os.stat(e.log_path).st_mode & 0o077, 0)
        self.assertEqual(os.stat(os.path.dirname(e.log_path)).st_mode & 0o077, 0)
        self.assertEqual(os.stat(e.script_path).st_mode & 0o077, 0)

        victim = os.path.join(self.home, "keep.sh")
        write(victim, "important")
        write(os.path.join(self.user_dir, "evil.desktop"),
              "[Desktop Entry]\nName=Evil\nExec=true\nX-Startup-Manager-Command=../../../../keep\n")
        evil = core.get_entry("evil.desktop")
        self.assertIsNone(evil.command_id)
        self.assertEqual(evil.kind, "app")
        core.remove_entry(evil)
        self.assertTrue(os.path.exists(victim))

    def test_script_runs_as_real_session_would(self):
        """Run exactly the Exec line gnome-session would, with the delay."""
        path = core.create_command("Touch", 'touch "$HOME/touched"', delay=1)
        e = core.get_entry(os.path.basename(path))
        start = time.time()
        subprocess.run(split_exec(e.df.get("Exec")), check=True, timeout=30)
        self.assertGreaterEqual(time.time() - start, 1.0)
        self.assertTrue(os.path.exists(os.path.join(self.home, "touched")))


if __name__ == "__main__":
    unittest.main()
