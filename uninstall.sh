#!/usr/bin/env bash
# Removes a Startup Manager that was installed with install.sh.
#   sudo bash uninstall.sh
# (Installed the .deb instead? Use:  sudo apt remove startup-manager)
#
# Your startup entries and custom commands are NOT touched: they keep working without the app.
set -euo pipefail

APP_ID="io.github.cyb3rl00m.StartupManager"

if [[ $EUID -ne 0 ]]; then
    echo "Please run with sudo:  sudo bash uninstall.sh"
    exit 1
fi

DEB_INSTALLED=0
if command -v dpkg-query >/dev/null \
   && dpkg-query -W -f='${Status}' startup-manager 2>/dev/null | grep -q "ok installed"; then
    DEB_INSTALLED=1
fi

PREFIXES=(/usr/local)
[[ -n "${PREFIX:-}" ]] && PREFIXES=("${PREFIX%/}" "${PREFIXES[@]}")

removed=0
for p in "${PREFIXES[@]}"; do
    # Files in /usr belong to the .deb if it is installed — leave them to apt.
    if [[ "$p" == "/usr" && $DEB_INSTALLED == 1 ]]; then
        continue
    fi
    if [[ -e "$p/lib/startup-manager" || -e "$p/bin/startup-manager" ]]; then
        rm -rf "$p/lib/startup-manager"
        rm -f "$p/bin/startup-manager" \
              "$p/share/applications/$APP_ID.desktop" \
              "$p/share/metainfo/$APP_ID.metainfo.xml" \
              "$p/share/icons/hicolor/scalable/apps/$APP_ID.svg"
        [[ -f "$p/share/icons/hicolor/icon-theme.cache" ]] && gtk-update-icon-cache -q -t "$p/share/icons/hicolor" 2>/dev/null || true
        update-desktop-database -q "$p/share/applications" 2>/dev/null || true
        echo "Removed Startup Manager from $p"
        removed=1
    fi
done

if [[ $DEB_INSTALLED == 1 ]]; then
    echo "The .deb package is still installed. Remove it with:  sudo apt remove startup-manager"
elif [[ $removed == 0 ]]; then
    echo "Startup Manager was not found — nothing to remove."
fi

echo
echo "Your startup entries (~/.config/autostart) and custom commands"
echo "(~/.local/share/startup-manager) were kept and still run at login."
echo "Turn things off first if you don't want them anymore, or delete those files by hand."
