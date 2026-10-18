#!/usr/bin/env bash
# Installs Startup Manager from source into /usr/local (the place for software that does not
# come from your package manager).
#
#   sudo bash install.sh                  # installs into /usr/local
#   sudo PREFIX=/opt/sm bash install.sh   # or somewhere else
#
# On Ubuntu/Debian you can use the .deb package from the releases page instead.
set -euo pipefail

APP_ID="io.github.cyb3rl00m.StartupManager"
SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PREFIX="${PREFIX:-/usr/local}"
PREFIX="${PREFIX%/}"

if [[ $EUID -ne 0 ]]; then
    echo "Please run with sudo:  sudo bash install.sh"
    exit 1
fi
if [[ "$PREFIX" != /* || "$PREFIX" == *[[:space:]#]* ]]; then
    echo "PREFIX must be an absolute path without spaces, e.g. /usr/local"
    exit 1
fi
if command -v dpkg-query >/dev/null \
   && dpkg-query -W -f='${Status}' startup-manager 2>/dev/null | grep -q "ok installed"; then
    echo "Startup Manager is already installed as a .deb package."
    echo "Use that (update it with a newer .deb), or remove it first:  sudo apt remove startup-manager"
    exit 1
fi

remove_from() {   # remove an install.sh installation from prefix $1
    local p="$1"
    rm -rf "$p/lib/startup-manager"
    rm -f "$p/bin/startup-manager" \
          "$p/share/applications/$APP_ID.desktop" \
          "$p/share/metainfo/$APP_ID.metainfo.xml" \
          "$p/share/icons/hicolor/scalable/apps/$APP_ID.svg"
}

echo "==> Installing dependencies (GTK 4, libadwaita, Python bindings)"
if [[ "${SKIP_DEPS:-0}" == "1" ]]; then
    echo "    skipped (SKIP_DEPS=1)"
elif command -v apt-get >/dev/null; then
    apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
elif command -v dnf >/dev/null; then
    dnf install -y python3 python3-gobject gtk4 libadwaita
elif command -v pacman >/dev/null; then
    pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita
elif command -v zypper >/dev/null; then
    zypper --non-interactive install python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1
else
    echo "Unknown package manager: please install Python 3 + PyGObject, GTK 4 and libadwaita yourself."
fi

echo "==> Copying files to $PREFIX"
remove_from "$PREFIX"
install -d -m 755 "$PREFIX/lib/startup-manager/startup_manager"
install -m 644 "$SRC"/src/startup_manager/*.py "$PREFIX/lib/startup-manager/startup_manager/"
python3 -m compileall -q "$PREFIX/lib/startup-manager" >/dev/null || true

install -D -m 755 "$SRC/startup-manager"                 "$PREFIX/bin/startup-manager"
install -D -m 644 "$SRC/data/$APP_ID.desktop"            "$PREFIX/share/applications/$APP_ID.desktop"
install -D -m 644 "$SRC/data/$APP_ID.metainfo.xml"       "$PREFIX/share/metainfo/$APP_ID.metainfo.xml"
install -D -m 644 "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
                  "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg"

for dir in "$PREFIX/share/icons/hicolor" /usr/share/icons/hicolor; do
    [[ -f "$dir/icon-theme.cache" ]] && gtk-update-icon-cache -q -t "$dir" 2>/dev/null || true
done
update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true

if [[ ":$PATH:" != *":$PREFIX/bin:"* ]]; then
    echo "Note: $PREFIX/bin is not in your PATH; start it from the app menu or run $PREFIX/bin/startup-manager"
fi
echo "==> Done. Open “Startup Manager” from your app menu, or run: startup-manager"
echo "    To remove it later:  sudo bash uninstall.sh"
