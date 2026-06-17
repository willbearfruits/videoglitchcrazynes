# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A desktop "lobotomy / anti-art" video glitch editor: a headless engine
(`glitchcore/`, no Qt) plus a PySide6 GUI (`gui/`), with a real ffmpeg/opencv
render backend. See `README.md` for the user-facing feature tour.

## Commands

```bash
python3 main.py                  # launch the GUI
# CLI batch render (>=2 positional args => CLI mode, else GUI):
python3 main.py in.mp4 out.mp4 --preset brainfuck [--datamosh] [--speed 1.5] [--seed 42]
```

- Requires **ffmpeg + ffprobe on PATH**. GPU encode uses `h264_nvenc` (falls
  back to libx264). Live features need system **portaudio** (sounddevice) and
  **v4l2loopback** (virtual cam); GPU shaders need a working GL context.
- Deps are in `requirements.txt` (`pip install -r requirements.txt`). `torch` is
  an optional extra (MiDaS depth only).
- **`./install.sh`** installs a desktop launcher (app menu + `~/Desktop`). It
  generates a `.desktop` pointing at the resolved `python3` and the repo dir —
  `Exec` uses the **absolute** interpreter path because `.desktop` files don't
  run a login shell (so a bare `python3` may not find the right env). Icon is
  `assets/icon.png`; the generated `assets/crazyglitch.desktop` is gitignored
  (machine-specific paths).
- **There is no test suite.** Verify changes with a headless smoke test that
  drives the engine or constructs the GUI offscreen, e.g.:
  ```bash
  QT_QPA_PLATFORM=offscreen python3 -c "from PySide6 import QtWidgets; \
    app=QtWidgets.QApplication([]); from gui.main_window import MainWindow; MainWindow()"
  ```
  GUI tests bypass file dialogs by monkeypatching (`win._pick_video = lambda: path`,
  `QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (path, ""))`)
  and wait on the async `BeatWorker.done` signal via a `QEventLoop`.

## Architecture (the parts that span multiple files)

**Engine vs GUI split.** Everything in `glitchcore/` is Qt-free and importable on
its own (the CLI uses it directly). `gui/` is a thin PySide6 layer on top. Keep
new processing logic in `glitchcore/` so it stays scriptable and headless-testable.

**Frames are BGR uint8** (opencv convention) end-to-end. Convert to RGB only at
the Qt display boundary (`gui/main_window.bgr_to_pixmap`).

**The Effect model is the core abstraction** (`glitchcore/effects.py`):
- Subclass `Effect`, declare `PARAMS` (dict of `ParamSpec`), implement
  `process(self, frame, ctx, clock, s)`, and decorate with `@register`. It
  auto-registers into `REGISTRY` / `EFFECT_ORDER`, and the GUI **auto-builds its
  controls** from `PARAMS` — no GUI code needed per effect.
- The base class `apply()` computes `s = beat_gate(ctx,clock) * amount *
  audio_mul(ctx)` and passes `s` (0..1) to `process`; the effect scales itself by
  `s`. Beat-sync (`beat_mode` always/pulse/gate + `beat_div`) and audio-reactive
  modulation (`mod_source` rms/bass/mid/high + `mod_depth`) are handled here, so
  every effect gets them for free.
- Effects are **stateful** (optical flow, echo, stutter keep buffers). Implement
  `reset()` to clear them; the renderer/preview calls `chain.reset()` before each
  run. The `make(name, **over)` factory only applies override keys listed in its
  handled-keys tuple — **add any new top-level Effect field there too**.

**Compositing pipeline:** `Chain` (ordered effects, per-frame) → `Layer`
(`comp.py`: a source + `start`/`trim_in`/`duration`/`warp`/`blend`/`opacity` + its
own `Chain`) → `Timeline` (composites layers bottom→top with `blend.py` modes). A
layer's source is a `VideoSource` (`sources.py`), a `Granulator` (`granular.py`),
or a live source (`live.py` webcam/screen). `warp.py` (`TimeWarp`) remaps a
layer's content time against a steady audio bed (beat-driven freeze/ramp/reverse);
`auto.lobotomize()` generates a warp + glitch chain.

**Timing & audio are passed through `ctx`** (`context.py FrameContext`).
`BeatClock` answers musical-timing queries from detected beats. `audio.AudioEnv`
(offline STFT envelopes) or `audio.LiveAudioEnv` (live input, same
`value(source,t)`/`scaled()` interface) is attached as `ctx.audio` so effects can
modulate on it. Beats/envelopes come from `BeatWorker` (a QThread running
librosa).

**Granular synthesis shares one schedule:** `Granulator.prepare()` builds a list
of `Grain`s; `Granulator.render()` draws the frame cloud and
`audio.granulate_audio()` synthesizes matching audio from the **same grains**, so
picture and sound granulate in lockstep.

**Audio in/out routing** (`audio.py`): the muxed render audio is separate from
**preview** playback. `AudioPlayer` plays a numpy buffer and resamples it to the
output device's rate (PortAudio doesn't resample). Its `device` can be a
sounddevice index, `None` (default), or `"pw"` — the `"pw"` path shells out to
`paplay --raw` so audio reaches **PipeWire** sinks (e.g. USB interfaces that
PortAudio can't enumerate because PipeWire holds them). A separate soundtrack can
be imported (`AudioImportWorker`, which works on audio-only files — it does *not*
call `media.probe`, which requires a video stream). Audio source precedence for
both preview and render mux: **imported track > granular layer audio > first
video layer's audio**.

**Rendering** (`renderer.py`): pipes processed frames to an ffmpeg subprocess
(`media.open_frame_writer`), optionally runs the real datamosh pass
(`datamosh.py` strips I-frames from an mpeg4 AVI — needs recurring I-frames, so
the encode uses a ~1/sec GOP), then muxes audio (`media.finalize`, which also
handles mp4/webm/gif + resolution scaling). `render()` is single-input;
`render_timeline()` renders a `Timeline`. Long renders run in `TimelineRenderWorker`
(QThread) with a serialized/owned chain so preview state isn't mutated.

**v2 subsystems:**
- **Motion** (`motion.py`): dense optical flow via OpenCV DIS (+ optional MiDaS
  depth behind `enable_midas()`); powers the `optimosh`/`flowsmear`/`depthpush`
  effects.
- **GPU shaders** (`gpu.py`): moderngl fragment shaders behind the `shaderfx`
  effect. **The GL context is thread-affine**, so the engine keeps one context
  per thread via `threading.local` — this is what lets shaders run in both the
  preview thread and the render QThread.
- **Node graph** (`graph.py` + `gui/node_editor.py`): an alternative DAG model
  (sources → effects → blends → output) with **feedback** — a `FeedbackNode`
  returns a tapped node's previous-frame output (every node stores `_prev` each
  frame), which breaks cycles and enables video-feedback trails. Currently
  preview-only (no file render).
- **Performance** (`output.py VirtualCam` + `LiveAudioEnv`): "Go Live" streams the
  composite to a v4l2loopback virtual webcam while reacting to live audio-in.

## GUI specifics worth knowing (`gui/main_window.py`)

- **Undo/redo is snapshot-based**, not command-based. `_snapshot()` captures each
  layer's editable state (props + `chain.to_dict()` + warp/gran dicts) while
  **keeping live `Layer`/source object refs**; `_restore()` reassembles
  `timeline.layers` from those refs. Mutating actions call `_push_undo()` first
  (`coalesce=True` time-debounces rapid slider drags). Consequence:
  `_remove_layer` must **not** release the layer's `VideoSource` (undo may restore
  it) — every source is tracked in `self._all_sources` and released only in
  `closeEvent`.
- **Render-time UI lock:** `_set_editing_enabled(False)` disables `_lock_widgets`
  during a render so the worker thread isn't racing live timeline edits.
- **Preview always fits the pane:** the preview is a custom `PreviewView` that
  paints the frame scaled-to-fit in `paintEvent` (composite res is fixed ~900px
  via `_canvas()`, decoupled from display size).
- **Space = play/pause** is handled by an app-level `eventFilter` (not a
  `QShortcut`) so a focused button can't swallow it; it's skipped when an
  editable widget has focus.
- **Persistence:** window geometry, splitter, volume, output device, render
  format/res, recent files, and last dir are saved via `QSettings("crazyglitch",
  "editor")` in `closeEvent`. Drag-and-drop onto the window adds video files as
  layers and audio files as the soundtrack.

## Gotchas

- **opencv shadows PySide6's Qt plugins.** Importing `cv2` (pulled in via
  `gui.main_window`) unconditionally points `QT_QPA_PLATFORM_PLUGIN_PATH` at
  opencv's bundled Qt5 plugins, shadowing PySide6's Qt6 `xcb` plugin → the GUI
  aborts with "Could not find the Qt platform plugin xcb" (reliably when launched
  from the `.desktop` entry, which has no shell to repair the fallback).
  `main.run_gui()` repoints the var at PySide6's own `platforms` dir **after** cv2
  is imported and **before** constructing `QApplication`. Keep that order if you
  touch the launcher.
- **Never `pkill -f main.py`** to stop the app — it matches other projects'
  `main.py` and even the killing shell's own command line. Find the PID by cwd
  (`readlink /proc/$pid/cwd`) and `kill` that exact number.
- This project has its **own git repo**; the parent `~/Projects` is a separate
  (workspace) repo — don't commit into it.
- Presets/projects/user-FX are JSON via `to_dict()`/`load()` on every model
  object; when you add a serializable field, update both ends.
- Headless GUI smoke tests that `start()` a QThread (`BeatWorker`,
  `AudioImportWorker`, render workers) may print `QThread: Destroyed while thread
  is still running` and `Aborted (core dumped)` at interpreter exit — that's a
  test-teardown artifact (the printed results above it are valid), not an app
  bug. `.wait()` the worker or ignore it.
- Offscreen test runs write `QSettings` (geometry from a 0-size window); clear
  `~/.config/crazyglitch` before launching the real GUI or it restores a bogus
  window size.
