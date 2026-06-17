# PyInstaller spec for the Crazy Video Glitch Editor.
# Built per-platform in CI (.github/workflows/release.yml).
#   pyinstaller packaging/crazyglitch.spec
# ffmpeg/ffprobe (if present in packaging/bin/) are bundled into bin/ so the
# frozen app finds them via media._resolve_bin without a system install.
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

APP = "CrazyVideoGlitchEditor"
ROOT = os.path.abspath(os.getcwd())

datas, binaries, hiddenimports = [], [], []

# Lazy-loaded / data-bearing packages PyInstaller's static scan tends to miss.
for pkg in ("librosa", "numba", "llvmlite", "sklearn", "scipy", "soundfile",
            "soxr", "pooch", "lazy_loader", "audioread", "joblib", "decorator",
            "msgpack", "sounddevice", "pygame", "moderngl", "glcontext"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all({pkg}) skipped: {e}")

hiddenimports += collect_submodules("glitchcore") + collect_submodules("gui")
hiddenimports += ["rtmidi", "cv2", "mss"]

# Bundle ffmpeg/ffprobe staged into packaging/bin/ by the CI workflow.
binroot = os.path.join(ROOT, "packaging", "bin")
if os.path.isdir(binroot):
    for fn in os.listdir(binroot):
        binaries.append((os.path.join(binroot, fn), "bin"))
        print(f"[spec] bundling binary: {fn}")

icon = os.environ.get("CRAZYGLITCH_ICON") or None

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP,
    console=False,
    disable_windowed_traceback=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APP + ".app",
        icon=icon,
        bundle_identifier="me.willbearfruits.crazyglitch",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSCameraUsageDescription": "Webcam layers and live capture.",
            "NSMicrophoneUsageDescription": "Live audio-reactive input.",
        },
    )
