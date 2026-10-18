#!/usr/bin/env bash
# Builds dist/startup-manager_<version>_all.deb  (Debian, Ubuntu, Mint, Pop!_OS …)
# Usage:  bash packaging/build-deb.sh          (no root needed)
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
APP_ID="io.github.cyb3rl00m.StartupManager"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/src/startup_manager/__init__.py")"
PKG="startup-manager"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

echo "==> Building $PKG $VERSION"

# --- files (same layout as install.sh) -------------------------------------
install -d "$STAGE/usr/lib/startup-manager/startup_manager"
install -m 644 "$ROOT"/src/startup_manager/*.py "$STAGE/usr/lib/startup-manager/startup_manager/"
install -D -m 755 "$ROOT/startup-manager"                 "$STAGE/usr/bin/startup-manager"
install -D -m 644 "$ROOT/data/$APP_ID.desktop"            "$STAGE/usr/share/applications/$APP_ID.desktop"
install -D -m 644 "$ROOT/data/$APP_ID.metainfo.xml"       "$STAGE/usr/share/metainfo/$APP_ID.metainfo.xml"
install -D -m 644 "$ROOT/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
                  "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -D -m 644 "$ROOT/README.md"    "$STAGE/usr/share/doc/$PKG/README.md"
install -D -m 644 "$ROOT/CHANGELOG.md" "$STAGE/usr/share/doc/$PKG/CHANGELOG.md"
install -D -m 644 "$ROOT/LICENSE"      "$STAGE/usr/share/doc/$PKG/copyright"

# --- control -----------------------------------------------------------------
SIZE_KB="$(du -sk "$STAGE" | cut -f1)"
install -d "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5)
Recommends: network-manager
Maintainer: cyb3rl00m <https://github.com/cyb3rl00m>
Homepage: https://github.com/cyb3rl00m/startup-manager
Description: choose which apps and commands run when you log in
 Startup Manager shows everything that starts when you log in and lets
 you change it with a switch: add installed apps (APT, Snap, Flatpak) or
 any program, pause, delay, edit or remove entries, and turn off entries
 that installed software added for everyone, for your account only.
 It can also run your own bash commands at login, with a syntax check,
 an optional delay, waiting for the network and saved output.
EOF

# Python caches may be created when the app runs; remove them on uninstall
cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
rm -rf /usr/lib/startup-manager/startup_manager/__pycache__
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/prerm"

# --- build -------------------------------------------------------------------
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" >/dev/null
echo "==> $DEB"
