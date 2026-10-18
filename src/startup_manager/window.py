"""Main window: an Apps tab and a Commands tab."""

from __future__ import annotations

import json
import os
import threading

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import APP_NAME, core
from .dialogs import AddAppDialog, CommandDialog, OutputDialog, ProgramDialog, make_icon

SETTINGS_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "startup-manager", "settings.json"
)


def _load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def _first_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return body.strip().splitlines()[0] if body.strip() else ""


def _escape(text: str) -> str:
    return GLib.markup_escape_text(text, -1)


class Page:
    """A scrollable, clamped column whose contents are rebuilt on refresh."""

    def __init__(self):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                           margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                           child=Adw.Clamp(maximum_size=760, child=self.box))

    def clear(self):
        child = self.box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.box.remove(child)
            child = nxt

    def add(self, widget):
        self.box.append(widget)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings = _load_settings()
        self.set_title(APP_NAME)
        self.set_size_request(360, 420)
        self.set_default_size(self.settings.get("width", 820), self.settings.get("height", 700))
        if self.settings.get("maximized"):
            self.maximize()
        self._refresh_source = 0
        self._reverting = False
        self._entries: dict[str, core.AutostartEntry] = {}

        # ----- layout -----
        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self.stack = Adw.ViewStack(vexpand=True)
        self.apps_page = Page()
        self.cmd_page = Page()
        self.stack.add_titled_with_icon(self.apps_page.scroller, "apps", "Apps", "view-app-grid-symbolic")
        self.stack.add_titled_with_icon(self.cmd_page.scroller, "commands", "Commands", "utilities-terminal-symbolic")
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

        self.header = Adw.HeaderBar()
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.narrow_title = Adw.WindowTitle(title=APP_NAME)
        self.header.set_title_widget(self.switcher)

        self.add_button = Gtk.Button(icon_name="list-add-symbolic", action_name="win.add")
        self.header.pack_start(self.add_button)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Show System Services", "win.show-services")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Refresh", "win.refresh")
        section.append("Open Autostart Folder", "win.open-autostart")
        section.append("Open Commands Folder", "win.open-commands")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(f"About {APP_NAME}", "app.about")
        menu.append_section(None, section)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                     primary=True, tooltip_text="Main Menu")
        self.header.pack_end(menu_button)

        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text="Search")
        self.header.pack_end(self.search_button)
        toolbar.add_top_bar(self.header)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search startup apps and commands")
        self.search_bar = Gtk.SearchBar(child=Adw.Clamp(maximum_size=500, child=self.search_entry))
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.set_key_capture_widget(self)
        self.search_button.bind_property("active", self.search_bar, "search-mode-enabled",
                                         GObject.BindingFlags.BIDIRECTIONAL)
        self.search_entry.connect("search-changed", lambda *_: self.refresh())
        toolbar.add_top_bar(self.search_bar)

        toolbar.set_content(self.stack)
        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.stack)
        toolbar.add_bottom_bar(self.switcher_bar)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 560sp"))
        breakpoint.connect("apply", self._on_narrow, True)
        breakpoint.connect("unapply", self._on_narrow, False)
        self.add_breakpoint(breakpoint)

        # ----- actions -----
        self._add_action("add", self._on_add)
        self._add_action("refresh", lambda *_: self.refresh())
        self._add_action("search", lambda *_: self.search_bar.set_search_mode(True))
        self._add_action("open-autostart", lambda *_: self._open_folder(core.user_autostart_dir()))
        self._add_action("open-commands", lambda *_: self._open_folder(core.commands_dir()))
        show = Gio.SimpleAction.new_stateful(
            "show-services", None, GLib.Variant.new_boolean(bool(self.settings.get("show_services")))
        )
        show.connect("change-state", self._on_show_services)
        self.add_action(show)
        for name, handler in (
            ("edit", self._on_edit),
            ("remove", self._on_remove),
            ("restore-default", self._on_restore_default),
            ("copy-command", self._on_copy_command),
            ("open-location", self._on_open_location),
            ("run-now", self._on_run_now),
            ("view-output", self._on_view_output),
        ):
            self._add_action(name, handler, "s")

        self.connect("close-request", self._on_close_request)

        # Refresh automatically when entries change behind our back
        # (GNOME Settings, Tweaks, another copy of this app, a text editor...).
        os.makedirs(core.user_autostart_dir(), exist_ok=True)
        self._monitor = Gio.File.new_for_path(core.user_autostart_dir()).monitor_directory(
            Gio.FileMonitorFlags.NONE, None
        )
        self._monitor.connect("changed", lambda *_: self.queue_refresh())

        self._on_page_changed()
        self.refresh()

    # ----- helpers ---------------------------------------------------------
    def _add_action(self, name, handler, param: str | None = None):
        action = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
        action.connect("activate", handler)
        self.add_action(action)
        return action

    def toast(self, text: str, button: str | None = None, on_button=None, timeout: int = 4):
        toast = Adw.Toast(title=_escape(text), timeout=timeout)
        if button and on_button:
            toast.set_button_label(button)
            toast.connect("button-clicked", lambda *_: on_button())
        self.toasts.add_toast(toast)
        return toast

    def error(self, text: str, exc: Exception | None = None):
        detail = f": {exc.strerror or exc}" if isinstance(exc, OSError) else (f": {exc}" if exc else "")
        self.toast(text + detail, timeout=6)

    def _entry(self, variant) -> core.AutostartEntry | None:
        filename = variant.get_string()
        entry = core.get_entry(filename)
        if entry is None:
            self.toast("That entry no longer exists.")
            self.refresh()
        return entry

    def _launch(self, gfile: Gio.File, containing: bool = False):
        launcher = Gtk.FileLauncher.new(gfile)

        def done(source, result):
            try:
                if containing:
                    source.open_containing_folder_finish(result)
                else:
                    source.launch_finish(result)
            except GLib.Error as err:
                self.toast(f"Could not open the file manager: {err.message}")

        if containing:
            launcher.open_containing_folder(self, None, done)
        else:
            launcher.launch(self, None, done)

    def _open_folder(self, path: str):
        os.makedirs(path, exist_ok=True)
        self._launch(Gio.File.new_for_path(path))

    def _on_narrow(self, _bp, narrow: bool):
        self.header.set_title_widget(self.narrow_title if narrow else self.switcher)
        self.switcher_bar.set_reveal(narrow)

    def _on_page_changed(self, *_):
        on_apps = self.stack.get_visible_child_name() != "commands"
        self.add_button.set_tooltip_text("Add Startup App" if on_apps else "Add Command")

    def _on_show_services(self, action, value):
        action.set_state(value)
        self.settings["show_services"] = value.get_boolean()
        self.refresh()

    def _on_close_request(self, *_):
        if not self.is_maximized():
            width, height = self.get_default_size()
            self.settings["width"], self.settings["height"] = width, height
        self.settings["maximized"] = self.is_maximized()
        _save_settings(self.settings)
        return False

    # ----- building the lists ----------------------------------------------
    def queue_refresh(self):
        if self._refresh_source:
            GLib.source_remove(self._refresh_source)
        self._refresh_source = GLib.timeout_add(250, self._refresh_timeout)

    def _refresh_timeout(self):
        self._refresh_source = 0
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        apps_pos = self.apps_page.scroller.get_vadjustment().get_value()
        cmd_pos = self.cmd_page.scroller.get_vadjustment().get_value()
        try:
            entries = core.list_entries()
        except OSError as exc:
            self.error("Could not read startup entries", exc)
            entries = []
        self._entries = {e.filename: e for e in entries}
        query = self.search_entry.get_text().strip().casefold()

        def matches(e: core.AutostartEntry) -> bool:
            if not query:
                return True
            hay = f"{e.name} {e.comment} {e.command} {e.filename}".casefold()
            return all(word in hay for word in query.split())

        show_services = bool(self.settings.get("show_services"))
        self._build_apps([e for e in entries if e.kind != "command" and matches(e)], show_services, query)
        self._build_commands([e for e in entries if e.kind == "command" and matches(e)], query)
        GLib.idle_add(self._restore_scroll, apps_pos, cmd_pos)

    def _restore_scroll(self, apps_pos, cmd_pos):
        self.apps_page.scroller.get_vadjustment().set_value(apps_pos)
        self.cmd_page.scroller.get_vadjustment().set_value(cmd_pos)
        return GLib.SOURCE_REMOVE

    def _no_results(self) -> Adw.StatusPage:
        return Adw.StatusPage(icon_name="edit-find-symbolic", title="No Results",
                              description="Try a different search.", vexpand=True)

    def _build_apps(self, entries, show_services: bool, query: str):
        page = self.apps_page
        page.clear()
        mine = [e for e in entries if e.kind == "app" and e.origin == "user"]
        system = [e for e in entries if e.kind == "app" and e.origin != "user"]
        services = [e for e in entries if e.kind == "service"] if show_services else []

        if query and not (mine or system or services):
            page.add(self._no_results())
            return

        group = Adw.PreferencesGroup(
            title="Your Startup Apps",
            description="These start each time you log in. Flip the switch to pause one without removing it.",
        )
        add = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label="Add App"),
                         valign=Gtk.Align.CENTER, action_name="win.add")
        add.add_css_class("flat")
        group.set_header_suffix(add)
        if mine:
            for e in mine:
                group.add(self._entry_row(e))
        elif not query:
            empty = Adw.ActionRow(title="No apps added yet",
                                  subtitle="Use Add App to start an app automatically when you log in.")
            empty.add_css_class("dim-label")
            group.add(empty)
        if mine or not query:
            page.add(group)

        if system:
            group = Adw.PreferencesGroup(
                title="Added by Installed Software",
                description="These start for everyone on this computer. You can turn them off for your account.",
            )
            for e in system:
                group.add(self._entry_row(e))
            page.add(group)

        if services:
            group = Adw.PreferencesGroup(
                title="System Services",
                description="Background parts of Ubuntu and the desktop, such as the keyring, input "
                            "methods and notifications. Only turn one off if you know what it does.",
            )
            for e in services:
                group.add(self._entry_row(e))
            page.add(group)
        elif not show_services and not query:
            hidden = sum(1 for e in self._entries.values() if e.kind == "service")
            if hidden:
                hint = Gtk.Label(
                    label=f"{hidden} system services are hidden. Show them from the main menu.",
                    wrap=True, justify=Gtk.Justification.CENTER,
                )
                hint.add_css_class("dim-label")
                hint.add_css_class("caption")
                page.add(hint)

    def _build_commands(self, entries, query: str):
        page = self.cmd_page
        page.clear()
        if not entries:
            if query:
                page.add(self._no_results())
                return
            button = Gtk.Button(label="Add Command", halign=Gtk.Align.CENTER, action_name="win.add")
            button.add_css_class("pill")
            button.add_css_class("suggested-action")
            page.add(Adw.StatusPage(
                icon_name="utilities-terminal-symbolic",
                title="No Custom Commands",
                description="Run your own bash commands every time you log in, for example to mount "
                            "a drive, start a sync script or send yourself a reminder.",
                child=button, vexpand=True,
            ))
            return
        group = Adw.PreferencesGroup(
            title="Custom Commands",
            description="Run with bash in the background each time you log in.",
        )
        add = Gtk.Button(child=Adw.ButtonContent(icon_name="list-add-symbolic", label="Add Command"),
                         valign=Gtk.Align.CENTER, action_name="win.add")
        add.add_css_class("flat")
        group.set_header_suffix(add)
        for e in entries:
            group.add(self._entry_row(e))
        page.add(group)

    def _entry_row(self, e: core.AutostartEntry) -> Adw.ActionRow:
        row = Adw.ActionRow(title=e.name, use_markup=False, title_lines=1, subtitle_lines=2)
        details: list[str] = []
        if e.kind == "command":
            row.add_prefix(make_icon("utilities-terminal-symbolic", "utilities-terminal-symbolic", 24))
            details.append(_first_line(core.read_command_body(e)) or "(empty)")
            if e.delay:
                details.append(f"after {e.delay} s")
            if e.wait_network:
                details.append("waits for network")
        else:
            row.add_prefix(make_icon(e.icon, "application-x-executable"))
            details.append(e.comment or e.command or e.filename)
            if e.delay:
                details.append(f"starts {e.delay} s after login")
            if e.condition:
                details.append("only when a setting allows it")
            if e.origin == "override":
                details.append("changed from system default")
        row.set_subtitle(" · ".join(details))
        row.set_tooltip_text(e.command or e.filename)

        if e.program_missing:
            warn = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            warn.add_css_class("warning")
            warn.set_tooltip_text(f"Program not found: {core.command_program(e.command)}")
            row.add_suffix(warn)

        target = GLib.Variant.new_string(e.filename)
        if e.kind == "command":
            run = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Run Now", action_name="win.run-now", action_target=target)
            run.add_css_class("flat")
            row.add_suffix(run)

        switch = Gtk.Switch(active=e.enabled, valign=Gtk.Align.CENTER)
        switch.connect("notify::active", self._on_switch, e.filename)
        row.add_suffix(switch)
        row.set_activatable_widget(switch)

        menu = Gio.Menu()
        main = Gio.Menu()
        if e.kind == "command":
            self._menu_item(main, "Edit…", "win.edit", target)
            self._menu_item(main, "Run Now", "win.run-now", target)
            self._menu_item(main, "View Output", "win.view-output", target)
            self._menu_item(main, "Open Script Location", "win.open-location", target)
        else:
            self._menu_item(main, "Edit…", "win.edit", target)
            self._menu_item(main, "Copy Command", "win.copy-command", target)
            self._menu_item(main, "Open File Location", "win.open-location", target)
        menu.append_section(None, main)
        danger = Gio.Menu()
        if e.origin == "override":
            self._menu_item(danger, "Restore Default", "win.restore-default", target)
        if e.can_remove and e.origin != "override":
            self._menu_item(danger, "Remove", "win.remove", target)
        if danger.get_n_items():
            menu.append_section(None, danger)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER,
                              tooltip_text="More")
        more.add_css_class("flat")
        row.add_suffix(more)
        return row

    @staticmethod
    def _menu_item(menu: Gio.Menu, label: str, action: str, target):
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(action, target)
        menu.append_item(item)

    # ----- switch ----------------------------------------------------------
    def _set_switch(self, switch: Gtk.Switch, active: bool):
        self._reverting = True
        try:
            switch.set_active(active)
        finally:
            self._reverting = False

    def _on_switch(self, switch, _pspec, filename):
        if self._reverting:
            return
        entry = core.get_entry(filename)
        want = switch.get_active()
        if entry is None:
            self.refresh()
            return
        if entry.enabled == want:
            return
        if entry.kind == "service" and not want:
            dialog = Adw.AlertDialog(
                heading=f"Turn Off “{entry.name}”?",
                body="This is part of the desktop. Turning it off can break features until you "
                     "turn it back on and log in again. It only affects your account.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("off", "Turn Off")
            dialog.set_response_appearance("off", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            def on_response(_d, response):
                if response == "off":
                    self._apply_enabled(entry, False, switch)
                else:
                    self._set_switch(switch, True)

            dialog.connect("response", on_response)
            dialog.present(self)
            return
        self._apply_enabled(entry, want, switch)

    def _apply_enabled(self, entry, enabled: bool, switch: Gtk.Switch):
        try:
            core.set_enabled(entry, enabled)
        except OSError as exc:
            self._set_switch(switch, not enabled)
            self.error(f"Could not change “{entry.name}”", exc)
            return
        self.queue_refresh()

    # ----- adding ----------------------------------------------------------
    def _on_add(self, *_):
        if self.stack.get_visible_child_name() == "commands":
            self._new_command()
            return
        existing = set(self._entries)
        AddAppDialog(self, existing, self._add_app, self._new_program)

    def _add_app(self, app: core.InstalledApp):
        try:
            path = core.add_app(app)
        except OSError as exc:
            self.error(f"Could not add “{app.name}”", exc)
            return
        self.refresh()
        filename = os.path.basename(path)
        self.toast(f"“{app.name}” will start when you log in", "Undo", lambda: self._undo_add(filename))

    def _undo_add(self, filename: str):
        entry = core.get_entry(filename)
        if entry and entry.can_remove:
            core.remove_entry(entry)
            self.refresh()

    def _new_program(self, name: str = "", cmd: str = ""):
        def save(name, cmd, comment, delay):
            try:
                path = core.add_custom_program(name, cmd, comment, delay)
            except OSError as exc:
                self.error(f"Could not add “{name}”", exc)
                return
            self.refresh()
            self.toast(f"“{name}” will start when you log in", "Undo",
                       lambda: self._undo_add(os.path.basename(path)))

        dialog = ProgramDialog(self, save, on_use_command=self._program_to_command)
        if name or cmd:
            dialog.name_row.set_text(name)
            dialog.cmd_row.set_text(cmd)

    def _program_to_command(self, name: str, cmd: str):
        self.stack.set_visible_child_name("commands")
        self._new_command(name, cmd)

    def _new_command(self, name: str = "", body: str = ""):
        def save(name, body, delay, wait_net):
            try:
                path = core.create_command(name, body, delay, wait_net)
            except OSError as exc:
                self.error(f"Could not save “{name}”", exc)
                return
            self.refresh()
            filename = os.path.basename(path)
            self.toast(f"“{name}” will run when you log in", "Run Now",
                       lambda: self._on_run_now(None, GLib.Variant.new_string(filename)))

        CommandDialog(self, save, name=name, body=body)

    # ----- per-entry actions -------------------------------------------------
    def _on_edit(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        if entry.kind == "command":
            def save_cmd(name, body, delay, wait_net):
                try:
                    core.update_command(entry, name, body, delay, wait_net)
                except OSError as exc:
                    self.error(f"Could not save “{name}”", exc)
                    return
                self.refresh()
                self.toast(f"Saved “{name}”")

            CommandDialog(self, save_cmd, entry=entry)
        else:
            def save_app(name, cmd, comment, delay):
                try:
                    core.update_entry(entry, name, cmd, comment, delay)
                except OSError as exc:
                    self.error(f"Could not save “{name}”", exc)
                    return
                self.refresh()
                self.toast(f"Saved “{name}”")

            ProgramDialog(self, save_app, entry=entry)

    def _on_remove(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        try:
            undo = core.remove_entry(entry)
        except (OSError, PermissionError) as exc:
            self.error(f"Could not remove “{entry.name}”", exc)
            return
        self.refresh()
        self.toast(f"Removed “{entry.name}”", "Undo", lambda: self._undo(undo))

    def _on_restore_default(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        try:
            undo = core.restore_default(entry)
        except (OSError, ValueError) as exc:
            self.error(f"Could not restore “{entry.name}”", exc)
            return
        self.refresh()
        self.toast(f"Restored the system default for “{entry.name}”", "Undo", lambda: self._undo(undo))

    def _undo(self, undo: core.UndoInfo):
        try:
            core.restore(undo)
        except OSError as exc:
            self.error("Could not undo", exc)
        self.refresh()

    def _on_copy_command(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        text = core.describe_command_for_shell(entry.command)
        provider = Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8",
                                                     GLib.Bytes.new(text.encode("utf-8")))
        self.get_clipboard().set_content(provider)
        self.toast("Command copied")

    def _on_open_location(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        path = entry.script_path or entry.path
        self._launch(Gio.File.new_for_path(path), containing=True)

    def _on_run_now(self, _action, variant):
        entry = self._entry(variant)
        if entry is None:
            return
        try:
            proc = core.run_command_now(entry)
        except OSError as exc:
            self.error(f"Could not run “{entry.name}”", exc)
            return
        filename = entry.filename
        name = entry.name
        self.toast(f"Running “{name}”…", timeout=2)

        def wait():
            code = proc.wait()
            GLib.idle_add(finished, code)

        def finished(code):
            text = f"“{name}” finished" if code == 0 else f"“{name}” failed with exit code {code}"
            self.toast(text, "View Output",
                       lambda: self._on_view_output(None, GLib.Variant.new_string(filename)),
                       timeout=6)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=wait, daemon=True).start()

    def _on_view_output(self, _action, variant):
        entry = self._entry(variant)
        if entry is not None:
            OutputDialog(self, entry)
