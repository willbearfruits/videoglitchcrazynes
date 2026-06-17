# Building the standalone app

The Linux AppImage is built automatically in CI (`.github/workflows/release.yml`)
and attached to the GitHub Release on every `v*` tag. Windows and macOS are
currently built off-CI with the steps below — the recipe mirrors the CI jobs, so
the artifacts match.

All builds use the one shared spec, `packaging/crazyglitch.spec`, which bundles
`ffmpeg`/`ffprobe` from `packaging/bin/` into the app so the download runs with
nothing else installed.

## Windows (PowerShell)

Needs Python 3.11 and 7-Zip/Expand-Archive. Run from the repo root:

```powershell
python -m pip install --upgrade pip wheel
pip install -r requirements.txt pyinstaller pillow

# bundle ffmpeg + ffprobe (BtbN static build)
Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile ff.zip
Expand-Archive ff.zip -DestinationPath ffdir -Force
New-Item -ItemType Directory -Force packaging/bin | Out-Null
Get-ChildItem -Recurse ffdir -Include ffmpeg.exe,ffprobe.exe | ForEach-Object { Copy-Item $_.FullName packaging/bin/ }

# app icon (.ico)
python -c "from PIL import Image; Image.open('assets/icon.png').save('packaging/icon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
$env:CRAZYGLITCH_ICON = "packaging/icon.ico"

# build + package
pyinstaller --noconfirm packaging/crazyglitch.spec
Compress-Archive -Path dist/CrazyVideoGlitchEditor -DestinationPath CrazyVideoGlitchEditor-windows-x64.zip
```

Then attach it to the release so the site's Windows download button resolves:

```powershell
gh release upload v0.1.0 CrazyVideoGlitchEditor-windows-x64.zip
```

The site links to `releases/latest/download/CrazyVideoGlitchEditor-windows-x64.zip`,
so the file name must match exactly.

## Linux (what CI runs)

```bash
pip install -r requirements.txt pyinstaller pillow
# static ffmpeg
wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar xf ffmpeg-release-amd64-static.tar.xz
mkdir -p packaging/bin
cp ffmpeg-*-amd64-static/ffmpeg ffmpeg-*-amd64-static/ffprobe packaging/bin/ && chmod +x packaging/bin/*

pyinstaller --noconfirm packaging/crazyglitch.spec
packaging/build-appimage.sh CrazyVideoGlitchEditor-linux-x86_64.AppImage
```

## macOS (for later)

```bash
pip install -r requirements.txt pyinstaller pillow
mkdir -p packaging/bin
for b in ffmpeg ffprobe; do curl -sL "https://evermeet.cx/ffmpeg/getrelease/$b/zip" -o "$b.zip"; unzip -o "$b.zip" -d packaging/bin; done
chmod +x packaging/bin/*

# .icns icon
mkdir -p icon.iconset
for s in 16 32 64 128 256 512; do
  sips -z $s $s assets/icon.png --out "icon.iconset/icon_${s}x${s}.png"
  sips -z $((s*2)) $((s*2)) assets/icon.png --out "icon.iconset/icon_${s}x${s}@2x.png"
done
iconutil -c icns icon.iconset -o packaging/icon.icns
export CRAZYGLITCH_ICON=packaging/icon.icns

pyinstaller --noconfirm packaging/crazyglitch.spec
ditto -c -k --keepParent dist/CrazyVideoGlitchEditor.app CrazyVideoGlitchEditor-macos.zip
```

The build is unsigned, so first launch is right-click → Open (or
`xattr -dr com.apple.quarantine CrazyVideoGlitchEditor.app`).
