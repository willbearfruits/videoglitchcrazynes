#!/usr/bin/env bash
# Install a desktop launcher (app menu + desktop) for the Crazy Video Glitch Editor.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
APPS="$HOME/.local/share/applications"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
mkdir -p "$APPS"

TMP="$(mktemp)"
cat > "$TMP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Crazy Video Glitch Editor
GenericName=Video Glitch Editor
Comment=Lobotomy / anti-art video glitch editor — layers, granular, datamosh, live VJ
Exec=$PY $DIR/main.py
Path=$DIR
Icon=$DIR/assets/icon.png
Terminal=false
Categories=AudioVideo;Video;AudioVideoEditing;
Keywords=glitch;video;editor;vj;datamosh;granular;lobotomy;
StartupNotify=true
EOF

install -m 755 "$TMP" "$APPS/crazyglitch.desktop"
[ -d "$DESK" ] && install -m 755 "$TMP" "$DESK/crazyglitch.desktop"
rm -f "$TMP"
update-desktop-database "$APPS" 2>/dev/null || true

echo "Installed launcher to:"
echo "  $APPS/crazyglitch.desktop"
[ -d "$DESK" ] && echo "  $DESK/crazyglitch.desktop"
echo "On KDE: if the desktop icon shows a warning, right-click it -> 'Allow Launching'."
