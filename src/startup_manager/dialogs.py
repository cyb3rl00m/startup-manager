"""Dialogs: add an app, edit a program entry, edit a command, view output."""

from __future__ import annotations

import os

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import core
from .desktopfile import DesktopFile, quote_exec_arg, strip_field_codes


def make_icon(name: str | None, fallback: str, size: int = 32) -> Gtk.Image:
    gicon = None
    if name and os.path.isabs(name):
        if os.path.exists(name):
            gicon = Gio.FileIcon.new(Gio.File.new_for_path(name))
    elif name:
        gicon = Gio.ThemedIcon.new_from_names([name, fallback])
    image = Gtk.Image.new_from_gicon(gicon or Gio.ThemedIcon.new(fallback))
    image.set_pixel_size(size)
    return image


def _dialog_shell(title: str, ok_label: str | None, width: int, height: int):
    """Adw.Dialog with Cancel/OK header buttons. Returns (dialog, toolbar, ok_button)."""
    dialog = Adw.Dialog(title=title, content_width=width, content_height=height)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    ok = None
    if ok_label:
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: dialog.close())
        header.pack_start(cancel)
        ok = Gtk.Button(label=ok_label)
        ok.add_css_class("suggested-action")
        header.pack_end(ok)
        dialog.set_default_widget(ok)
    toolbar.add_top_bar(header)
    dialog.set_child(toolbar)
    return dialog, toolbar, ok


def _note(text: str = "", css: str = "dim-label") -> Gtk.Label:
    label = Gtk.Label(label=text, wrap=True, xalign=0, margin_top=6)
    label.add_css_class("caption")
    if css:
        label.add_css_class(css)
    return label


# --------------------------------------------------------------------------
# Add an installed app
# --------------------------------------------------------------------------
class AddAppDialog:
    """Lists installed apps; picking one makes it start at login."""

    def __init__(self, parent: Gtk.Widget, existing: set[str], on_pick, on_custom):
        self.on_pick = on_pick
        self.on_custom = on_custom
        self.dialog, toolbar, _ = _dialog_shell("Add Startup App", None, 500, 640)

        self.search = Gtk.SearchEntry(placeholder_text="Search installed apps", hexpand=True)
        search_box = Gtk.Box(margin_start=12, margin_end=12, margin_bottom=6)
        search_box.append(self.search)
        toolbar.add_top_bar(search_box)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_top=12, margin_bottom=18, margin_start=12, margin_end=12)

        custom_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        custom_list.add_css_class("boxed-list")
        custom_row = Adw.ActionRow(title="Custom Program…", activatable=True, use_markup=False,
                                   subtitle="Start any program or script by its command")
        custom_row.add_prefix(make_icon("list-add-symbolic", "list-add-symbolic", 24))
        custom_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        custom_row.connect("activated", self._on_custom)
        custom_list.append(custom_row)
        content.append(custom_list)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_filter_func(self._filter)
        self.listbox.set_placeholder(_note("No apps match your search.", "dim-label"))
        self._rows: dict[Gtk.Widget, str] = {}
        for app in core.list_installed_apps():
            row = Adw.ActionRow(title=app.name, use_markup=False, title_lines=1, subtitle_lines=1)
            row.set_subtitle(app.comment or app.command)
            row.add_prefix(make_icon(app.icon, "application-x-executable"))
            if app.desktop_id in existing:
                row.set_subtitle("Already in your startup list")
                row.add_suffix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
                row.set_sensitive(False)
            else:
                source = Gtk.Label(label=app.source, valign=Gtk.Align.CENTER)
                source.add_css_class("dim-label")
                source.add_css_class("caption")
                row.add_suffix(source)
                row.set_activatable(True)
                row.connect("activated", self._on_row, app)
            self._rows[row] = f"{app.name} {app.comment} {app.command} {app.desktop_id}".casefold()
            self.listbox.append(row)
        content.append(self.listbox)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=560, child=content))
        toolbar.set_content(scroller)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", self._activate_first)
        self.dialog.present(parent)
        self.search.grab_focus()

    def _filter(self, row) -> bool:
        query = self.search.get_text().strip().casefold()
        return not query or all(word in self._rows.get(row, "") for word in query.split())

    def _activate_first(self, *_):
        row = self.listbox.get_first_child()
        while row is not None:
            if isinstance(row, Gtk.ListBoxRow) and row.get_child_visible() and row.get_sensitive():
                row.activate()
                return
            row = row.get_next_sibling()

    def _on_row(self, _row, app):
        self.dialog.close()
        self.on_pick(app)

    def _on_custom(self, *_):
        self.dialog.close()
        self.on_custom()


# --------------------------------------------------------------------------
# Custom program / edit an app entry
# --------------------------------------------------------------------------
class ProgramDialog:
    """Create a custom program entry, or edit any app entry."""

    def __init__(self, parent: Gtk.Widget, on_save, entry: core.AutostartEntry | None = None,
                 on_use_command=None):
        self.entry = entry
        self.on_save = on_save
        self.on_use_command = on_use_command
        title = "Edit Startup App" if entry else "Custom Program"
        self.dialog, toolbar, self.ok = _dialog_shell(title, "Save" if entry else "Add", 500, 560)
        self.ok.connect("clicked", self._on_ok)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        if entry and entry.origin in ("system", "override"):
            group.set_description(
                "This entry comes with the system. Your changes are saved as your own copy, "
                "and Restore Default brings the original back."
            )
        self.name_row = Adw.EntryRow(title="Name")
        self.cmd_row = Adw.EntryRow(title="Command")
        browse = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Choose a program file")
        browse.add_css_class("flat")
        browse.connect("clicked", self._on_browse)
        self.cmd_row.add_suffix(browse)
        self.comment_row = Adw.EntryRow(title="Description (optional)")
        for row in (self.name_row, self.cmd_row, self.comment_row):
            group.add(row)
        page.add(group)

        self.hint = _note("", "")
        self.hint.set_visible(False)
        self.use_cmd_button = Gtk.Button(label="Add as Custom Command Instead", halign=Gtk.Align.START,
                                         margin_top=6, visible=False)
        self.use_cmd_button.add_css_class("pill")
        self.use_cmd_button.connect("clicked", self._on_use_command)
        hint_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hint_box.append(self.hint)
        hint_box.append(self.use_cmd_button)
        group.add(hint_box)

        options = Adw.PreferencesGroup(title="Options")
        self.delay_row = Adw.SpinRow.new_with_range(0, 600, 5)
        self.delay_row.set_title("Delay (seconds)")
        self.delay_row.set_subtitle("Wait this long after login before starting")
        options.add(self.delay_row)
        page.add(options)
        toolbar.set_content(page)

        if entry:
            self.name_row.set_text(entry.name)
            self.cmd_row.set_text(entry.command)
            self.comment_row.set_text(entry.comment)
            self.delay_row.set_value(entry.delay)
        for row in (self.name_row, self.cmd_row):
            row.connect("changed", self._validate)
        self._validate()
        self.dialog.present(parent)
        self.name_row.grab_focus()

    def _validate(self, *_):
        name = self.name_row.get_text().strip()
        cmd = self.cmd_row.get_text().strip()
        self.ok.set_sensitive(bool(name and cmd))
        msg, css, show_switch = "", "", False
        unchanged = self.entry is not None and cmd == self.entry.command
        if cmd and core.looks_like_shell(cmd) and not unchanged:
            msg = ("This looks like a shell command (pipes, variables, ~, && or redirects). "
                   "Those only work as a Custom Command, on the Commands tab.")
            css, show_switch = "warning", self.on_use_command is not None
        elif cmd and not core.command_exists(cmd):
            prog = core.command_program(cmd) or cmd
            msg = f"“{prog}” was not found. Check the spelling or use the full path."
            css = "warning"
        self.hint.set_text(msg)
        self.hint.set_visible(bool(msg))
        for c in ("warning", "error"):
            self.hint.remove_css_class(c)
        if css:
            self.hint.add_css_class(css)
        self.use_cmd_button.set_visible(show_switch)

    def _on_browse(self, *_):
        dialog = Gtk.FileDialog(title="Choose a Program", modal=True)
        dialog.open(self.dialog.get_root(), None, self._on_browse_done)

    def _on_browse_done(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path() if gfile else None
        if not path:
            return
        if path.endswith(".desktop"):
            df = DesktopFile.load(path)
            cmd = strip_field_codes(df.get("Exec") or "")
            if not self.name_row.get_text().strip():
                self.name_row.set_text(df.get_localized("Name") or "")
        elif path.endswith(".sh") and not os.access(path, os.X_OK):
            cmd = f"bash {quote_exec_arg(path)}"
        else:
            cmd = quote_exec_arg(path)
        self.cmd_row.set_text(cmd)
        if not self.name_row.get_text().strip():
            self.name_row.set_text(os.path.splitext(os.path.basename(path))[0])

    def _on_use_command(self, *_):
        name, cmd = self.name_row.get_text().strip(), self.cmd_row.get_text().strip()
        self.dialog.close()
        self.on_use_command(name, cmd)

    def _on_ok(self, *_):
        self.dialog.close()
        self.on_save(
            self.name_row.get_text().strip(),
            self.cmd_row.get_text().strip(),
            self.comment_row.get_text().strip(),
            int(self.delay_row.get_value()),
        )


# --------------------------------------------------------------------------
# Custom bash command
# --------------------------------------------------------------------------
class CommandDialog:
    def __init__(self, parent: Gtk.Widget, on_save, entry: core.AutostartEntry | None = None,
                 name: str = "", body: str = ""):
        self.on_save = on_save
        self._check_source = 0
        title = "Edit Command" if entry else "New Command"
        self.dialog, toolbar, self.ok = _dialog_shell(title, "Save" if entry else "Add", 560, 680)
        self.ok.connect("clicked", self._on_ok)
        self.dialog.connect("closed", self._on_closed)

        page = Adw.PreferencesPage()
        name_group = Adw.PreferencesGroup()
        self.name_row = Adw.EntryRow(title="Name")
        name_group.add(self.name_row)
        page.add(name_group)

        code_group = Adw.PreferencesGroup(
            title="Bash Commands",
            description="Runs with bash each time you log in. Use as many lines as you like.",
        )
        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=10, bottom_margin=10, left_margin=10, right_margin=10,
                            accepts_tab=True)
        scroller = Gtk.ScrolledWindow(child=view, min_content_height=200, max_content_height=360,
                                      propagate_natural_height=True)
        frame = Gtk.Frame(child=scroller)
        frame.add_css_class("view")
        code_group.add(frame)
        self.status = _note("", "")
        code_group.add(self.status)
        page.add(code_group)

        options = Adw.PreferencesGroup(title="Options")
        self.delay_row = Adw.SpinRow.new_with_range(0, 600, 5)
        self.delay_row.set_title("Delay (seconds)")
        self.delay_row.set_subtitle("Wait this long after login before running")
        self.net_row = Adw.SwitchRow(title="Wait for Network",
                                     subtitle="Wait up to 60 seconds for a connection first")
        options.add(self.delay_row)
        options.add(self.net_row)
        page.add(options)

        info = Adw.PreferencesGroup()
        info.add(_note(
            "Commands run as you, in the background, without a terminal window, so password "
            "prompts such as sudo will not work. Everything they print is saved and can be "
            "seen with View Output."
        ))
        page.add(info)
        toolbar.set_content(page)

        if entry:
            name = entry.name
            body = core.read_command_body(entry)
            self.delay_row.set_value(entry.delay)
            self.net_row.set_active(entry.wait_network)
        self.name_row.set_text(name)
        self.buffer.set_text(body)
        self.name_row.connect("changed", self._update_ok)
        self.buffer.connect("changed", self._on_body_changed)
        self._update_ok()
        self.dialog.present(parent)
        (view if name else self.name_row).grab_focus()

    def _body(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    def _update_ok(self, *_):
        self.ok.set_sensitive(bool(self.name_row.get_text().strip() and self._body().strip()))

    def _on_body_changed(self, *_):
        self._update_ok()
        if self._check_source:
            GLib.source_remove(self._check_source)
        self._check_source = GLib.timeout_add(700, self._run_check)

    def _run_check(self) -> bool:
        self._check_source = 0
        self._check()
        return GLib.SOURCE_REMOVE

    def _check(self) -> bool:
        body = self._body()
        self.status.remove_css_class("error")
        self.status.remove_css_class("success")
        if not body.strip():
            self.status.set_text("")
            return False
        ok, msg = core.check_bash_syntax(body)
        if ok:
            self.status.set_text("✓ No syntax errors found")
            self.status.add_css_class("success")
        else:
            self.status.set_text(msg)
            self.status.add_css_class("error")
        return ok

    def _on_closed(self, *_):
        if self._check_source:
            GLib.source_remove(self._check_source)
            self._check_source = 0

    def _on_ok(self, *_):
        if not self._check():
            return
        self.dialog.close()
        self.on_save(
            self.name_row.get_text().strip(),
            self._body(),
            int(self.delay_row.get_value()),
            self.net_row.get_active(),
        )


# --------------------------------------------------------------------------
# Command output
# --------------------------------------------------------------------------
class OutputDialog:
    def __init__(self, parent: Gtk.Widget, entry: core.AutostartEntry):
        self.entry = entry
        self.dialog, toolbar, _ = _dialog_shell(f"Output: {entry.name}", None, 640, 520)
        bar = Gtk.Box(spacing=6, margin_start=12, margin_end=12, margin_bottom=6)
        self.info = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.info.add_css_class("dim-label")
        self.info.add_css_class("caption")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self.load())
        clear = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Clear Output")
        clear.add_css_class("flat")
        clear.connect("clicked", self._on_clear)
        bar.append(self.info)
        bar.append(refresh)
        bar.append(clear)
        toolbar.add_top_bar(bar)

        self.stack = Gtk.Stack()
        self.buffer = Gtk.TextBuffer()
        self.view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12, bottom_margin=12,
                                 left_margin=12, right_margin=12)
        self.scroller = Gtk.ScrolledWindow(child=self.view, vexpand=True)
        self.stack.add_named(self.scroller, "log")
        empty = Adw.StatusPage(icon_name="utilities-terminal-symbolic", title="No Output Yet",
                               description="Output appears here after the command runs at login "
                                           "or with Run Now.")
        self.stack.add_named(empty, "empty")
        toolbar.set_content(self.stack)
        self.load()
        self.dialog.present(parent)

    def load(self):
        text = core.read_log(self.entry)
        self.buffer.set_text(text)
        self.stack.set_visible_child_name("log" if text.strip() else "empty")
        self.info.set_text(self.entry.log_path or "")
        GLib.idle_add(self._scroll_end)

    def _scroll_end(self):
        adj = self.scroller.get_vadjustment()
        adj.set_value(adj.get_upper())
        return GLib.SOURCE_REMOVE

    def _on_clear(self, *_):
        core.clear_log(self.entry)
        self.load()
