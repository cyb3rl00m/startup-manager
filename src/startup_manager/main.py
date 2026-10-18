import sys

from . import APP_ID, APP_NAME, WEBSITE, __version__

INSTALL_HINT = """\
Startup Manager needs Python bindings for GTK 4 and libadwaita (1.5 or newer).
Install them with:

  Ubuntu, Debian, Mint, Pop!_OS:  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
  Fedora:                         sudo dnf install python3-gobject gtk4 libadwaita
  Arch, Manjaro, EndeavourOS:     sudo pacman -S python-gobject gtk4 libadwaita
  openSUSE:                       sudo zypper install python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
"""


def _load_gtk():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, Gtk

    if (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) < (1, 5):
        raise ImportError(f"libadwaita {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION} is too old")
    return Adw, Gio, Gtk


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv[1:]:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--help" in argv[1:] or "-h" in argv[1:]:
        print(f"Usage: startup-manager [--version]\n\n{APP_NAME} {__version__}: "
              "choose which apps and commands run when you log in.\n" + WEBSITE)
        return 0
    try:
        Adw, Gio, Gtk = _load_gtk()
    except (ImportError, ValueError) as exc:
        print(f"Could not start {APP_NAME}: {exc}\n", file=sys.stderr)
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    from .window import MainWindow

    class StartupManagerApp(Adw.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        def do_startup(self):
            Adw.Application.do_startup(self)
            for name, callback, accels in (
                ("quit", lambda *_: self.quit(), ["<Control>q"]),
                ("about", self._on_about, []),
            ):
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", callback)
                self.add_action(action)
                if accels:
                    self.set_accels_for_action(f"app.{name}", accels)
            self.set_accels_for_action("win.add", ["<Control>n"])
            self.set_accels_for_action("win.search", ["<Control>f"])
            self.set_accels_for_action("win.refresh", ["F5", "<Control>r"])
            self.set_accels_for_action("window.close", ["<Control>w"])

        def do_activate(self):
            win = self.get_active_window() or MainWindow(application=self)
            win.present()

        def _on_about(self, *_):
            about = Adw.AboutDialog(
                application_name=APP_NAME,
                application_icon=APP_ID,
                developer_name="cyb3rl00m",
                version=__version__,
                website=WEBSITE,
                issue_url=WEBSITE + "/issues",
                comments="Choose which apps and commands run when you log in.",
                license_type=Gtk.License.MIT_X11,
                developers=["cyb3rl00m https://github.com/cyb3rl00m"],
            )
            about.add_credit_section("Made with", ["Claude by Anthropic https://claude.ai"])
            about.present(self.get_active_window())

    return StartupManagerApp().run(argv)
