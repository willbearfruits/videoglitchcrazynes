#!/usr/bin/env bash
# Wrap the PyInstaller onedir build (dist/CrazyVideoGlitchEditor) into a single
# portable AppImage. Run from the repo root after pyinstaller.
#   packaging/build-appimage.sh [output.AppImage]
set -euo pipefail

APP=CrazyVideoGlitchEditor
DIST="dist/$APP"
OUT="${1:-$APP-x86_64.AppImage}"

[ -d "$DIST" ] || { echo "missing $DIST — run pyinstaller first"; exit 1; }

rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/icons/hicolor/256x256/apps
cp -r "$DIST" AppDir/usr/bin/
cp assets/icon.png AppDir/crazyglitch.png
cp assets/icon.png AppDir/usr/share/icons/hicolor/256x256/apps/crazyglitch.png

cat > AppDir/crazyglitch.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Crazy Video Glitch Editor
Comment=Beat-synced video glitch editor — datamosh, granular, audio-reactive
Exec=CrazyVideoGlitchEditor
Icon=crazyglitch
Categories=AudioVideo;Video;AudioVideoEditing;
Terminal=false
DESKTOP

cat > AppDir/AppRun <<'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/CrazyVideoGlitchEditor/CrazyVideoGlitchEditor" "$@"
APPRUN
chmod +x AppDir/AppRun

TOOL=appimagetool-x86_64.AppImage
if [ ! -x "$TOOL" ]; then
  wget -q "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" -O "$TOOL"
  chmod +x "$TOOL"
fi

# runners have no FUSE — extract-and-run instead of mounting
ARCH=x86_64 ./"$TOOL" --appimage-extract-and-run AppDir "$OUT"
echo "built $OUT"
