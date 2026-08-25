#!/bin/bash
# Installs the app icon and a .desktop launcher entry for the current user.
set -euo pipefail
cd "$(dirname "$0")"

install -Dm644 data/icon.png ~/.local/share/icons/hicolor/512x512/apps/org.shayne.AudiobookOffline.png

desktop_dir=~/.local/share/applications
install -Dm644 data/org.shayne.AudiobookOffline.desktop "$desktop_dir/org.shayne.AudiobookOffline.desktop"
sed -i "s|^Exec=.*|Exec=bash -c 'cd $(pwd) \&\& python3 -m absplayer.app'|" "$desktop_dir/org.shayne.AudiobookOffline.desktop"

command -v gtk4-update-icon-cache >/dev/null && gtk4-update-icon-cache -f -t ~/.local/share/icons/hicolor 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database "$desktop_dir" || true

echo "Installed. The app should now appear in your launcher as \"Audiobook Offline\"."
