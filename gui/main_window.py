"""CRAZY VIDEO GLITCH EDITOR — layered, timelined, granular, with live sound."""
from __future__ import annotations
import json
import os
import cv2

RENDER_DIR = os.path.expanduser("~/Videos/glitch-renders")
import numpy as np
from PySide6 import QtWidgets, QtCore, QtGui

from glitchcore import presets, blend as blendmod
from glitchcore import audio as A
from glitchcore import effects as fx
from glitchcore.comp import Timeline, Layer
from glitchcore.sources import VideoSource
from glitchcore.granular import Granulator
from glitchcore.warp import TimeWarp
from glitchcore.auto import lobotomize as do_lobotomize
from glitchcore.context import BeatClock
from glitchcore.renderer import RenderOptions
from glitchcore import beat as beatmod

from glitchcore.live import WebcamSource, ScreenSource, find_webcam_index

from .widgets import EffectCard, GranularPanel, LivePanel
from .timeline import BeatBar
from .render_worker import BeatWorker, TimelineRenderWorker
from .live_input import InputHub

PREVIEW_W = 600


def bgr_to_pixmap(bgr) -> QtGui.QPixmap:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
    return QtGui.QPixmap.fromImage(img.copy())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CRAZY VIDEO GLITCH EDITOR")
        self.resize(1320, 820)

        self.timeline = Timeline(fps=30.0)
        self.beats, self.onsets = [], []
        self.audio_env = None
        self.clock = BeatClock([], 30.0)
        self.selected: Layer | None = None
        self.t = 0.0
        self.cards: list[EffectCard] = []
        self.audio_player = A.AudioPlayer()
        self._audio_cache: dict[str, tuple] = {}
        self.render_worker = None
        self.beat_worker = None
        self.input_hub = None
        self.live_cam = None
        self.live_audio_env = None
        self._prev_env = None
        self._layer_count = 0

        self._build_ui()
        self._timers()
        self._style()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._lock_widgets = []        # disabled while a render thread runs
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)

        tb = QtWidgets.QHBoxLayout()
        b_vid = QtWidgets.QPushButton("➕ Video Layer")
        b_vid.clicked.connect(self.add_video_layer)
        b_gran = QtWidgets.QPushButton("➕ Granular Layer")
        b_gran.clicked.connect(self.add_granular_layer)
        b_cam = QtWidgets.QPushButton("➕ Webcam")
        b_cam.clicked.connect(self.add_webcam_layer)
        b_scr = QtWidgets.QPushButton("➕ Screen")
        b_scr.clicked.connect(self.add_screen_layer)
        tb.addWidget(b_vid)
        tb.addWidget(b_gran)
        tb.addWidget(b_cam)
        tb.addWidget(b_scr)
        tb.addWidget(self._sep())
        tb.addWidget(QtWidgets.QLabel("Preset→layer:"))
        self.preset_cb = QtWidgets.QComboBox()
        tb.addWidget(self.preset_cb)
        b_pre = QtWidgets.QPushButton("Load")
        b_pre.clicked.connect(self.apply_preset)
        tb.addWidget(b_pre)
        b_savefx = QtWidgets.QPushButton("Save FX")
        b_savefx.setToolTip("Save the selected layer's effect chain as a reusable preset")
        b_savefx.clicked.connect(self.save_fx)
        tb.addWidget(b_savefx)
        b_lobo = QtWidgets.QPushButton("🧠 Lobotomize")
        b_lobo.setToolTip("Auto-generate a beat-synced time-warp + glitch chain "
                          "on the selected video layer")
        b_lobo.clicked.connect(self.lobotomize_selected)
        tb.addWidget(b_lobo)
        tb.addWidget(self._sep())
        tb.addWidget(QtWidgets.QLabel("Add fx:"))
        self.add_cb = QtWidgets.QComboBox()
        for name in fx.EFFECT_ORDER:
            self.add_cb.addItem(fx.REGISTRY[name].label, name)
        tb.addWidget(self.add_cb)
        b_add = QtWidgets.QPushButton("+")
        b_add.setFixedWidth(32)
        b_add.clicked.connect(self.add_effect)
        tb.addWidget(b_add)
        tb.addStretch(1)
        b_node = QtWidgets.QPushButton("🕸 Node Graph")
        b_node.setToolTip("Open the node-graph editor (sources → effects → "
                          "blends → feedback loops → output)")
        b_node.clicked.connect(self.open_node_editor)
        tb.addWidget(b_node)
        b_save = QtWidgets.QPushButton("Save")
        b_save.clicked.connect(self.save_project)
        b_load = QtWidgets.QPushButton("Open Project")
        b_load.clicked.connect(self.load_project)
        tb.addWidget(b_save)
        tb.addWidget(b_load)
        outer.addLayout(tb)
        for i in range(tb.count()):       # lock all toolbar controls during render
            wdg = tb.itemAt(i).widget()
            if isinstance(wdg, (QtWidgets.QPushButton, QtWidgets.QComboBox)):
                self._lock_widgets.append(wdg)

        split = QtWidgets.QSplitter()
        outer.addWidget(split, 1)

        # ---- left: preview + transport ----
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.preview = QtWidgets.QLabel(
            "Add a Video Layer to start.\n\n"
            "➕ Video Layer = a clip   ·   ➕ Granular Layer = frame-grain cloud\n"
            "Stack layers, set blend modes, add effects, hit RENDER.")
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_W, 338)
        self.preview.setStyleSheet("background:#000; color:#777; border:1px solid #222;")
        lv.addWidget(self.preview, 1)
        self.timebar = BeatBar()
        self.timebar.seek.connect(self.seek_fraction)
        lv.addWidget(self.timebar)
        tr = QtWidgets.QHBoxLayout()
        self.play_btn = QtWidgets.QPushButton("▶ Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setEnabled(False)
        tr.addWidget(self.play_btn)
        self.scrub = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.scrub.setRange(0, 1000)
        self.scrub.sliderMoved.connect(lambda v: self.seek_fraction(v / 1000.0))
        tr.addWidget(self.scrub, 1)
        self.mute_cb = QtWidgets.QCheckBox("🔊")
        self.mute_cb.setChecked(True)
        tr.addWidget(self.mute_cb)
        self.time_lbl = QtWidgets.QLabel("0.0 / 0.0s")
        tr.addWidget(self.time_lbl)
        lv.addLayout(tr)
        split.addWidget(left)

        # ---- right: layers + tabs + render ----
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self._layers_box())
        self.tabs = QtWidgets.QTabWidget()
        # effects tab
        self.fx_scroll = QtWidgets.QScrollArea()
        self.fx_scroll.setWidgetResizable(True)
        self.stack_host = QtWidgets.QWidget()
        self.stack_lay = QtWidgets.QVBoxLayout(self.stack_host)
        self.stack_lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.stack_lay.setSpacing(6)
        self.fx_scroll.setWidget(self.stack_host)
        self.tabs.addTab(self.fx_scroll, "Effects")
        # granular tab
        self.gran_scroll = QtWidgets.QScrollArea()
        self.gran_scroll.setWidgetResizable(True)
        self.gran_host = QtWidgets.QWidget()
        self.gran_lay = QtWidgets.QVBoxLayout(self.gran_host)
        self.gran_lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.gran_scroll.setWidget(self.gran_host)
        self.tabs.addTab(self.gran_scroll, "Granular")
        # live tab = performance (Go Live) + control mapping
        self.live_panel = LivePanel()
        self.live_panel.enable.toggled.connect(self._toggle_live)
        self.live_panel.applied.connect(self._on_live_applied)
        live_container = QtWidgets.QWidget()
        lc = QtWidgets.QVBoxLayout(live_container)
        lc.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        lc.addWidget(self._perf_box())
        lc.addWidget(self.live_panel)
        live_scroll = QtWidgets.QScrollArea()
        live_scroll.setWidgetResizable(True)
        live_scroll.setWidget(live_container)
        self.tabs.addTab(live_scroll, "Live")
        rv.addWidget(self.tabs, 1)
        rv.addWidget(self._render_box())
        split.addWidget(right)
        split.setSizes([680, 640])

        self._lock_widgets += [self.tabs, self.play_btn, self.scrub]
        self._refresh_presets()
        self.status = self.statusBar()
        self.status.showMessage("Ready. Add a Video Layer.")

    def _set_editing_enabled(self, on):
        for w in self._lock_widgets:
            w.setEnabled(on)

    def _refresh_presets(self):
        cur = self.preset_cb.currentText()
        self.preset_cb.blockSignals(True)
        self.preset_cb.clear()
        self.preset_cb.addItems(list(presets.PRESETS.keys()))
        user = presets.list_user()
        if user:
            self.preset_cb.insertSeparator(self.preset_cb.count())
            self.preset_cb.addItems(user)
        i = self.preset_cb.findText(cur)
        if i >= 0:
            self.preset_cb.setCurrentIndex(i)
        self.preset_cb.blockSignals(False)

    def _layers_box(self):
        box = QtWidgets.QGroupBox("Layers  (bottom → top)")
        v = QtWidgets.QVBoxLayout(box)
        self.layer_list = QtWidgets.QListWidget()
        self.layer_list.setMaximumHeight(120)
        self.layer_list.currentRowChanged.connect(self._row_selected)
        v.addWidget(self.layer_list)
        self._lock_widgets.append(self.layer_list)
        btns = QtWidgets.QHBoxLayout()
        for txt, slot in (("▲", lambda: self._move_layer(-1)),
                          ("▼", lambda: self._move_layer(1)),
                          ("Remove", self._remove_layer)):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(slot)
            btns.addWidget(b)
            self._lock_widgets.append(b)
        v.addLayout(btns)

        props = QtWidgets.QGridLayout()
        self.p_enabled = QtWidgets.QCheckBox("Enabled")
        self.p_enabled.toggled.connect(self._prop_changed)
        props.addWidget(self.p_enabled, 0, 0)
        props.addWidget(QtWidgets.QLabel("Blend"), 0, 1)
        self.p_blend = QtWidgets.QComboBox()
        self.p_blend.addItems(blendmod.MODES)
        self.p_blend.currentTextChanged.connect(self._prop_changed)
        props.addWidget(self.p_blend, 0, 2)
        props.addWidget(QtWidgets.QLabel("Opacity"), 1, 0)
        self.p_opacity = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.p_opacity.setRange(0, 100)
        self.p_opacity.setValue(100)
        self.p_opacity.valueChanged.connect(self._prop_changed)
        props.addWidget(self.p_opacity, 1, 1, 1, 2)
        props.addWidget(QtWidgets.QLabel("Start s"), 2, 0)
        self.p_start = QtWidgets.QDoubleSpinBox()
        self.p_start.setRange(0, 600)
        self.p_start.setSingleStep(0.1)
        self.p_start.valueChanged.connect(self._prop_changed)
        props.addWidget(self.p_start, 2, 1)
        props.addWidget(QtWidgets.QLabel("Trim s"), 2, 2)
        self.p_trim = QtWidgets.QDoubleSpinBox()
        self.p_trim.setRange(0, 600)
        self.p_trim.setSingleStep(0.1)
        self.p_trim.valueChanged.connect(self._prop_changed)
        props.addWidget(self.p_trim, 2, 3)
        props.addWidget(QtWidgets.QLabel("Len s"), 3, 0)
        self.p_len = QtWidgets.QDoubleSpinBox()
        self.p_len.setRange(0, 600)
        self.p_len.setSingleStep(0.5)
        self.p_len.setSpecialValueText("full")     # 0 displays "full"
        self.p_len.setToolTip("Layer length on the timeline (0 = full source). "
                              "Use this to trim long webcam/screen layers.")
        self.p_len.valueChanged.connect(self._prop_changed)
        props.addWidget(self.p_len, 3, 1)
        self._props = [self.p_enabled, self.p_blend, self.p_opacity,
                       self.p_start, self.p_trim, self.p_len]
        v.addLayout(props)
        return box

    def _render_box(self):
        box = QtWidgets.QGroupBox("Render")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("Speed"), 0, 0)
        self.speed = QtWidgets.QDoubleSpinBox()
        self.speed.setRange(0.1, 8.0)
        self.speed.setSingleStep(0.25)
        self.speed.setValue(1.0)
        g.addWidget(self.speed, 0, 1)
        g.addWidget(QtWidgets.QLabel("Format"), 0, 2)
        self.fmt_cb = QtWidgets.QComboBox()
        self.fmt_cb.addItems(["mp4", "webm", "gif"])
        g.addWidget(self.fmt_cb, 0, 3)
        self.datamosh_cb = QtWidgets.QCheckBox("Datamosh")
        g.addWidget(self.datamosh_cb, 1, 0, 1, 2)
        g.addWidget(QtWidgets.QLabel("Res"), 1, 2)
        self.res_cb = QtWidgets.QComboBox()
        self.res_cb.addItems(["Source", "1080p", "720p", "480p"])
        g.addWidget(self.res_cb, 1, 3)
        self.progress = QtWidgets.QProgressBar()
        g.addWidget(self.progress, 2, 0, 1, 2)
        self.render_btn = QtWidgets.QPushButton("⚡ RENDER")
        self.render_btn.clicked.connect(self.do_render)
        self.render_btn.setEnabled(False)
        g.addWidget(self.render_btn, 2, 2)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_render)
        self.cancel_btn.setEnabled(False)
        g.addWidget(self.cancel_btn, 2, 3)
        return box

    def _perf_box(self):
        box = QtWidgets.QGroupBox("Performance — live output")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("Audio in"), 0, 0)
        self.audio_in_cb = QtWidgets.QComboBox()
        self.audio_in_cb.addItem("default", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    self.audio_in_cb.addItem(d["name"][:34], i)
        except Exception:
            pass
        g.addWidget(self.audio_in_cb, 0, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel("Out res"), 1, 0)
        self.live_res_cb = QtWidgets.QComboBox()
        self.live_res_cb.addItems(["960x540", "1280x720", "640x360", "1920x1080"])
        self.live_res_cb.setCurrentText("1280x720")
        g.addWidget(self.live_res_cb, 1, 1)
        self.golive_btn = QtWidgets.QPushButton("🔴 Go Live  →  virtual cam")
        self.golive_btn.setCheckable(True)
        self.golive_btn.setToolTip("Stream the live composite to a virtual webcam "
                                   "(OBS/Zoom/browser) + react to live audio in")
        self.golive_btn.toggled.connect(self._toggle_golive)
        g.addWidget(self.golive_btn, 1, 2)
        self.live_status = QtWidgets.QLabel("offline")
        g.addWidget(self.live_status, 2, 0, 1, 3)
        return box

    def _sep(self):
        s = QtWidgets.QFrame()
        s.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        return s

    def _timers(self):
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._refresh = QtCore.QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.timeout.connect(self._composite_now)
        self._gran_timer = QtCore.QTimer(self)
        self._gran_timer.setSingleShot(True)
        self._gran_timer.timeout.connect(self._reprepare_and_audio)

    def _style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#1e1e1e; color:#ddd; font-size:12px; }
            QPushButton { background:#2d2d2d; border:1px solid #3a3a3a;
                padding:5px 9px; border-radius:4px; }
            QPushButton:hover { background:#383838; }
            QPushButton:disabled { color:#666; }
            #EffectCard { background:#262626; border:1px solid #383838;
                border-radius:6px; }
            QComboBox, QSpinBox, QDoubleSpinBox { background:#2d2d2d;
                border:1px solid #3a3a3a; padding:3px; border-radius:3px; }
            QGroupBox { border:1px solid #383838; border-radius:6px;
                margin-top:8px; padding-top:8px; }
            QGroupBox::title { subcontrol-origin:margin; left:8px; }
            QTabWidget::pane { border:1px solid #383838; }
            QTabBar::tab { background:#262626; padding:5px 12px; }
            QTabBar::tab:selected { background:#383838; }
            QListWidget { background:#262626; border:1px solid #383838; }
            QProgressBar { background:#2d2d2d; border:1px solid #3a3a3a;
                border-radius:3px; text-align:center; }
            QProgressBar::chunk { background:#00e5ff; }
            QSlider::groove:horizontal { height:4px; background:#3a3a3a; border-radius:2px; }
            QSlider::handle:horizontal { background:#00e5ff; width:12px;
                margin:-5px 0; border-radius:6px; }
        """)

    # --------------------------------------------------------- canvas size
    def _canvas(self):
        w = PREVIEW_W
        if self.timeline.width:
            h = int(w * self.timeline.height / self.timeline.width)
        else:
            h = 338
        return w, max(1, h)

    # ----------------------------------------------------------- add layers
    def _pick_video(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Pick a video", "", "Video (*.mp4 *.mov *.mkv *.avi *.webm *.gif);;All (*)")
        return path

    def _add_source_layer(self, src, kind, detect_path=None):
        """Common path for video/webcam/screen layers."""
        self._layer_count += 1
        layer = Layer(f"{kind} {self._layer_count}", source=src)
        first_video = not any(not l.is_granular for l in self.timeline.layers)
        self.timeline.add(layer)
        if first_video:
            self.timeline.fps = src.fps or 30.0
            self.timeline.width, self.timeline.height = src.w, src.h
            if detect_path:
                self._detect_beats(detect_path)
            else:                                      # live source: no audio
                self.beats = beatmod.grid_beats(src.duration, 120.0)
                self.onsets, self.audio_env = [], None
                self.clock = BeatClock(self.beats, self.timeline.fps)
                self.timebar.set_beats(self.beats, [], src.duration)
        self._reprepare_granular()
        self._refresh_layer_list(select=layer)
        self.play_btn.setEnabled(True)
        self.render_btn.setEnabled(True)
        self._reprepare_and_audio()
        self.seek_fraction(0.0)
        self.status.showMessage(f"Added {layer.name}: {src.w}×{src.h} @ {src.fps:.0f}fps")
        return layer

    def add_video_layer(self):
        path = self._pick_video()
        if not path:
            return
        try:
            src = VideoSource(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        self._add_source_layer(src, "video", detect_path=path)

    def add_webcam_layer(self):
        idx = find_webcam_index()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "Webcam", "No working webcam found.")
            return
        src = WebcamSource(idx)
        if not src.ok():
            QtWidgets.QMessageBox.warning(self, "Webcam", f"Could not open webcam {idx}.")
            return
        self._add_source_layer(src, "webcam")

    def add_screen_layer(self):
        try:
            src = ScreenSource(1)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Screen", f"Screen capture failed:\n{e}")
            return
        self._add_source_layer(src, "screen")

    def add_granular_layer(self):
        path = self._pick_video()
        if not path:
            return
        gsrc = VideoSource(path)
        frames = gsrc.preload(work_w=480, max_frames=600)
        if not frames:
            QtWidgets.QMessageBox.critical(self, "Error", "No frames decoded.")
            return
        self._layer_count += 1
        g = Granulator(seed=4242 + self._layer_count)
        g.set_video(frames, gsrc.fps)
        if self.timeline.width == 0:
            self.timeline.width, self.timeline.height = gsrc.w, gsrc.h
            self.timeline.fps = gsrc.fps or 30.0
        layer = Layer(f"granular {self._layer_count}", granulator=g)
        layer.blend = "screen"
        layer._au = A.load_audio(path)   # (samples, sr) for granular sound
        layer._gpath = path
        gsrc.release()
        self.timeline.add(layer)
        if not self.beats:
            self._detect_beats(path)
        self._reprepare_granular()
        self._refresh_layer_list(select=layer)
        self.play_btn.setEnabled(True)
        self.render_btn.setEnabled(True)
        self._reprepare_and_audio()
        self.seek_fraction(0.0)
        self.status.showMessage(f"Added {layer.name} (granulating {path.split('/')[-1]})")

    # ------------------------------------------------------------- beats
    def _detect_beats(self, path):
        self.beat_worker = BeatWorker(path)
        self.beat_worker.done.connect(self._beats_ready)
        self.beat_worker.start()

    def _beats_ready(self, result):
        self.beats = result.get("beats", [])
        self.onsets = result.get("onsets", [])
        self.audio_env = result.get("env")
        self.clock = BeatClock(self.beats, self.timeline.fps)
        self._rebuild_warps()
        self.timebar.set_beats(self.beats, self.onsets, max(0.1, self.timeline.duration()))
        self.status.showMessage(
            f"{len(self.beats)} beats · {result.get('tempo',0):.0f} BPM")
        self._composite_now()

    # --------------------------------------------------------- granular prep
    def _video_span(self):
        return max((l.start + (l.source.duration if l.source else 0)
                    for l in self.timeline.layers if not l.is_granular and l.source),
                   default=0.0)

    def _reprepare_granular(self):
        vid = self._video_span()
        for l in self.timeline.layers:
            if l.is_granular:
                dur = l.duration or (vid if vid > 0 else 5.0)
                l.granulator.prepare(max(0.5, dur))
        self.clock = BeatClock(self.beats, self.timeline.fps)
        self.timebar.set_beats(self.beats, self.onsets, max(0.1, self.timeline.duration()))

    def _reprepare_and_audio(self):
        self._reprepare_granular()
        self._rebuild_warps()
        self._rebuild_audio()
        self._composite_now()

    # ----------------------------------------------------------- live audio
    def _load_src_audio(self, path):
        if path not in self._audio_cache:
            self._audio_cache[path] = A.load_audio(path)
        return self._audio_cache[path]

    def _rebuild_audio(self):
        buf, sr = None, 22050
        gl = next((l for l in reversed(self.timeline.layers)
                   if l.is_granular and l.enabled), None)
        if gl is not None and getattr(gl, "_au", (None,))[0] is not None:
            samples, sr = gl._au
            buf = A.granulate_audio(samples, sr, gl.granulator.grains,
                                    max(0.5, self.timeline.duration()))
        else:
            vl = next((l for l in self.timeline.layers
                       if not l.is_granular and l.enabled and l.source), None)
            if vl is not None:
                samples, sr = self._load_src_audio(vl.source.path)
                buf = samples
        self.audio_player.set_buffer(buf, sr)

    # ----------------------------------------------------------- layer list
    def _refresh_layer_list(self, select=None):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        # show top layer first (list top = composited last)
        for l in reversed(self.timeline.layers):
            tag = "◆" if l.is_granular else "▣"
            on = "" if l.enabled else "  (off)"
            self.layer_list.addItem(f"{tag} {l.name}  [{l.blend}]{on}")
        self.layer_list.blockSignals(False)
        if select is not None and select in self.timeline.layers:
            row = len(self.timeline.layers) - 1 - self.timeline.layers.index(select)
            self.layer_list.setCurrentRow(row)
        elif self.timeline.layers:
            self.layer_list.setCurrentRow(0)

    def _row_to_layer(self, row):
        if row < 0 or row >= len(self.timeline.layers):
            return None
        return self.timeline.layers[len(self.timeline.layers) - 1 - row]

    def _row_selected(self, row):
        self.selected = self._row_to_layer(row)
        self._load_props()
        self._rebuild_fx_tab()
        self._rebuild_gran_tab()
        self._update_live_targets()

    def _load_props(self):
        l = self.selected
        for w in self._props:
            w.blockSignals(True)
        if l is not None:
            self.p_enabled.setChecked(l.enabled)
            self.p_blend.setCurrentText(l.blend)
            self.p_opacity.setValue(int(l.opacity * 100))
            self.p_start.setValue(l.start)
            self.p_trim.setValue(l.trim_in)
            self.p_len.setValue(l.duration or 0.0)
        for w in self._props:
            w.blockSignals(False)

    def _prop_changed(self, *_):
        l = self.selected
        if l is None:
            return
        l.enabled = self.p_enabled.isChecked()
        l.blend = self.p_blend.currentText()
        l.opacity = self.p_opacity.value() / 100.0
        l.start = self.p_start.value()
        l.trim_in = self.p_trim.value()
        l.duration = self.p_len.value() or None      # 0 = full source
        # update the list label without losing selection
        row = self.layer_list.currentRow()
        item = self.layer_list.item(row)
        if item:
            tag = "◆" if l.is_granular else "▣"
            dur = f" {l.duration:.1f}s" if l.duration else ""
            item.setText(f"{tag} {l.name}  [{l.blend}]{dur}{'' if l.enabled else '  (off)'}")
        # start/length change the timeline span -> re-derive grains, warps, beats bar
        self._gran_timer.start(40)

    def _move_layer(self, delta):
        l = self.selected
        if l is None:
            return
        # list is reversed, so visual up = later in composite order
        i = self.timeline.layers.index(l)
        j = max(0, min(len(self.timeline.layers) - 1, i - delta))
        self.timeline.layers.insert(j, self.timeline.layers.pop(i))
        self._refresh_layer_list(select=l)
        self._composite_now()

    def _remove_layer(self):
        l = self.selected
        if l is None:
            return
        if l.source:
            l.source.release()
        self.timeline.layers.remove(l)
        self.selected = None
        self._refresh_layer_list()
        self._reprepare_and_audio()
        if not self.timeline.layers:
            self.play_btn.setEnabled(False)
            self.render_btn.setEnabled(False)

    # ----------------------------------------------------------- fx + gran tabs
    def _rebuild_fx_tab(self):
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        if self.selected is None:
            return
        for eff in self.selected.chain.effects:
            self._add_card(eff)
        self._update_live_targets()

    def _add_card(self, eff):
        card = EffectCard(eff)
        card.changed.connect(self._composite_now)
        card.remove_me.connect(self._remove_effect)
        card.move_me.connect(self._move_effect)
        self.cards.append(card)
        self.stack_lay.addWidget(card)

    def _rebuild_gran_tab(self):
        while self.gran_lay.count():
            it = self.gran_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if self.selected is None or not self.selected.is_granular:
            self.gran_lay.addWidget(QtWidgets.QLabel(
                "Select a Granular layer to granulate frames."))
            self.tabs.setTabEnabled(1, self.selected is not None and self.selected.is_granular)
            return
        self.tabs.setTabEnabled(1, True)
        panel = GranularPanel(self.selected.granulator)
        panel.changed.connect(lambda: self._gran_timer.start(40))
        self.gran_lay.addWidget(panel)

    def add_effect(self):
        if self.selected is None:
            return
        eff = fx.REGISTRY[self.add_cb.currentData()]()
        self.selected.chain.add(eff)
        self._add_card(eff)
        self._composite_now()

    def _remove_effect(self, eff):
        if self.selected:
            self.selected.chain.remove(eff)
            self._rebuild_fx_tab()
            self._composite_now()

    def _move_effect(self, eff, delta):
        if self.selected:
            self.selected.chain.move(eff, delta)
            self._rebuild_fx_tab()
            self._composite_now()

    # --------------------------------------------------------- live control
    def _toggle_live(self, on):
        if on:
            if self.input_hub is None:
                self.input_hub = InputHub()
                self.input_hub.control.connect(self.live_panel.handle)
                self.input_hub.status.connect(self.live_panel.dev_lbl.setText)
                self.input_hub.start()
        else:
            if self.input_hub is not None:
                self.input_hub.stop()
                self.input_hub.wait(500)
                self.input_hub = None
            self.live_panel.dev_lbl.setText("Live input off")

    def _update_live_targets(self):
        l = self.selected
        targets = []
        if l is not None:
            for i, e in enumerate(l.chain.effects):
                targets.append((f"fx{i} {e.label} · amount",
                                (lambda eff: lambda v: setattr(eff, "amount", v))(e)))
            if l.is_granular:
                g = l.granulator
                for key, spec in g.PARAMS.items():
                    mn, mx = spec.min, spec.max
                    targets.append((f"gran · {spec.label}",
                                    (lambda gg, k, a, b: lambda v:
                                     gg.v.__setitem__(k, a + v * (b - a)))(g, key, mn, mx)))
        self.live_panel.set_targets(targets)

    def _on_live_applied(self):
        if self.selected is not None and self.selected.is_granular:
            self._gran_timer.start(40)        # reprepare grains + audio (debounced)
        elif not self.timer.isActive():
            self._refresh.start(15)

    # --------------------------------------------------------- go live (VJ)
    def _toggle_golive(self, on):
        if on:
            if not self.timeline.layers:
                self.golive_btn.setChecked(False)
                QtWidgets.QMessageBox.information(self, "Go Live", "Add a layer first.")
                return
            try:
                from glitchcore.output import VirtualCam
                w, h = (int(x) for x in self.live_res_cb.currentText().split("x"))
                self.live_cam = VirtualCam(w, h, self.timeline.fps or 30.0)
            except Exception as e:
                self.golive_btn.setChecked(False)
                QtWidgets.QMessageBox.critical(
                    self, "Virtual cam",
                    f"Could not open virtual camera:\n{e}\n\n"
                    "Needs v4l2loopback (modprobe v4l2loopback).")
                return
            # live audio-reactive: swap the envelope for a live input one
            try:
                from glitchcore.audio import LiveAudioEnv
                self._prev_env = self.audio_env
                self.live_audio_env = LiveAudioEnv(
                    device=self.audio_in_cb.currentData()).start()
                self.audio_env = self.live_audio_env
            except Exception:
                self.live_audio_env = None
            if not self.timer.isActive():
                self.toggle_play()
            self.golive_btn.setText("⏹ Stop Live")
            self.live_status.setText(f"🔴 LIVE → {self.live_cam.device}  ({self.live_cam.w}×{self.live_cam.h})")
        else:
            if self.live_cam is not None:
                self.live_cam.close()
                self.live_cam = None
            if self.live_audio_env is not None:
                self.live_audio_env.stop()
                self.live_audio_env = None
                self.audio_env = self._prev_env
            self.golive_btn.setText("🔴 Go Live  →  virtual cam")
            self.live_status.setText("offline")

    def apply_preset(self):
        if self.selected is None:
            QtWidgets.QMessageBox.information(self, "No layer", "Select a layer first.")
            return
        name = self.preset_cb.currentText()
        if name in presets.PRESETS:
            self.selected.chain = presets.build(name, seed=self.selected.chain.seed)
            if name in presets.WANTS_DATAMOSH:
                self.datamosh_cb.setChecked(True)
        elif name in presets.list_user():
            self.selected.chain = presets.load_user(name)
        else:
            return
        self._rebuild_fx_tab()
        self._composite_now()
        self.status.showMessage(f"Loaded preset '{name}' onto {self.selected.name}")

    def save_fx(self):
        if self.selected is None:
            QtWidgets.QMessageBox.information(self, "Save FX", "Select a layer first.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save FX preset", "Preset name:")
        if ok and name.strip():
            saved = presets.save_user(name.strip(), self.selected.chain)
            self._refresh_presets()
            self.preset_cb.setCurrentText(saved)
            self.status.showMessage(f"Saved FX preset '{saved}'")

    def lobotomize_selected(self):
        l = self.selected
        if l is None or l.is_granular:
            QtWidgets.QMessageBox.information(
                self, "Lobotomize", "Select a video layer first.")
            return
        cd = l.source.duration if l.source else self.timeline.duration()
        do_lobotomize(l, self.beats, content_dur=cd,
                      duration=self.timeline.duration(), seed=l.chain.seed)
        self.datamosh_cb.setChecked(True)
        self._rebuild_fx_tab()
        self._composite_now()
        self.status.showMessage(f"🧠 Lobotomized {l.name} — time-warp + glitch chain")

    def _rebuild_warps(self):
        dur = self.timeline.duration()
        for l in self.timeline.layers:
            if l.warp is not None:
                cd = (l.granulator.out_dur if l.is_granular
                      else (l.source.duration if l.source else dur))
                l.warp.build(self.beats, dur, cd)

    # ------------------------------------------------------------- preview
    def _composite_now(self):
        if not self.timeline.layers:
            return
        if self.timer.isActive():
            return
        w, h = self._canvas()
        frame = self.timeline.render_frame(self.t, w, h, self.clock, audio=self.audio_env)
        self.preview.setPixmap(bgr_to_pixmap(frame))
        self._update_time()

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.audio_player.stop()
            self.play_btn.setText("▶ Play")
            return
        if self.t >= self.timeline.duration() - 1e-3:
            self.t = 0.0
        for l in self.timeline.layers:
            l.chain.reset()
        if self.mute_cb.isChecked():
            self.audio_player.play_from(self.t)
        self.timer.start(int(1000 / max(1, self.timeline.fps)))
        self.play_btn.setText("⏸ Pause")

    def _tick(self):
        self.t += 1.0 / max(1, self.timeline.fps)
        if self.t >= self.timeline.duration():
            self.t = 0.0
            for l in self.timeline.layers:
                l.chain.reset()
            if self.mute_cb.isChecked() and self.live_cam is None:
                self.audio_player.play_from(0.0)
        if self.live_cam is not None:
            # composite at the cam's resolution, stream it, show a scaled preview
            frame = self.timeline.render_frame(self.t, self.live_cam.w, self.live_cam.h,
                                               self.clock, audio=self.audio_env)
            self.live_cam.send(frame)
            pw, ph = self._canvas()
            self.preview.setPixmap(bgr_to_pixmap(cv2.resize(frame, (pw, ph))))
        else:
            w, h = self._canvas()
            frame = self.timeline.render_frame(self.t, w, h, self.clock, audio=self.audio_env)
            self.preview.setPixmap(bgr_to_pixmap(frame))
        self._update_time()

    def seek_fraction(self, f):
        dur = self.timeline.duration()
        if dur <= 0:
            return
        if self.timer.isActive():
            self.toggle_play()
        self.t = max(0.0, min(dur - 1e-3, f * dur))
        for l in self.timeline.layers:
            l.chain.reset()
        self._composite_now()

    def _update_time(self):
        dur = max(1e-6, self.timeline.duration())
        self.time_lbl.setText(f"{self.t:0.1f} / {dur:0.1f}s")
        self.timebar.set_playhead(self.t)
        if not self.scrub.isSliderDown():
            self.scrub.setValue(int(self.t / dur * 1000))

    # -------------------------------------------------------------- render
    def do_render(self):
        if not self.timeline.layers:
            return
        fmt = self.fmt_cb.currentText()
        out, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Render to", os.path.join(RENDER_DIR, f"glitched.{fmt}"),
            f"Video (*.{fmt})")
        if not out:
            return
        if not out.lower().endswith("." + fmt):
            out += "." + fmt
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        if self.timer.isActive():
            self.toggle_play()
        height = {"Source": 0, "1080p": 1080, "720p": 720, "480p": 480}[
            self.res_cb.currentText()]
        opts = RenderOptions(speed=self.speed.value(),
                             datamosh=self.datamosh_cb.isChecked(), gpu=True,
                             out_format=fmt, height=height)
        # audio: prefer granular, else first video source
        au, sr, asrc = None, 22050, None
        gl = next((l for l in reversed(self.timeline.layers)
                   if l.is_granular and l.enabled), None)
        if gl is not None and getattr(gl, "_au", (None,))[0] is not None:
            samples, sr = gl._au
            au = A.granulate_audio(samples, sr, gl.granulator.grains,
                                   max(0.5, self.timeline.duration()))
        else:
            vl = next((l for l in self.timeline.layers
                       if not l.is_granular and l.source), None)
            asrc = vl.source.path if vl else None
        self.render_worker = TimelineRenderWorker(
            self.timeline, out, self.beats, opts,
            audio_buffer=au, audio_sr=sr, audio_src_path=asrc,
            audio_env=self.audio_env)
        self.render_worker.progress.connect(self._render_progress)
        self.render_worker.finished_ok.connect(self._render_done)
        self.render_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._set_editing_enabled(False)   # lock layer/structure edits during render
        self.render_worker.start()

    def _render_progress(self, frac, msg):
        self.progress.setValue(int(frac * 100))
        self.status.showMessage(msg)

    def _render_done(self, ok, msg):
        self.render_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._set_editing_enabled(True)
        self.progress.setValue(100 if ok else 0)
        if ok:
            self.status.showMessage(f"✓ {msg}")
            QtWidgets.QMessageBox.information(self, "Done", f"Saved:\n{msg}")
        else:
            self.status.showMessage(msg)

    def cancel_render(self):
        if self.render_worker:
            self.render_worker.cancel()

    # ------------------------------------------------------------- project
    def open_node_editor(self):
        from .node_editor import NodeEditor
        if not self.timeline.layers:
            QtWidgets.QMessageBox.information(
                self, "Node Graph", "Add at least one layer first (its source feeds the graph).")
            return
        self._node_editor = NodeEditor(self)
        self._node_editor.show()

    def save_project(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save project", "glitch.json", "Project (*.json)")
        if not path:
            return
        data = {"fps": self.timeline.fps,
                "width": self.timeline.width, "height": self.timeline.height,
                "speed": self.speed.value(), "datamosh": self.datamosh_cb.isChecked(),
                "layers": [l.to_dict() for l in self.timeline.layers]}
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.status.showMessage(f"Saved {path}")

    def load_project(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open project", "", "Project (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Open project", f"Could not read project:\n{e}")
            return
        from glitchcore.chain import Chain
        self.timeline = Timeline(fps=data.get("fps", 30.0))
        self.timeline.width = data.get("width", 0)
        self.timeline.height = data.get("height", 0)
        self.speed.setValue(data.get("speed", 1.0))
        self.datamosh_cb.setChecked(data.get("datamosh", False))
        skipped = []
        for ld in data.get("layers", []):
            try:
                if ld.get("is_granular"):
                    g = Granulator().load(ld.get("granulator", {}))
                    gp = ld.get("path") or ld.get("_gpath")
                    if gp:
                        gs = VideoSource(gp)
                        g.set_video(gs.preload(work_w=480), gs.fps)
                        gs.release()
                    layer = Layer(ld.get("name", "granular"), granulator=g)
                    if gp:
                        layer._au = A.load_audio(gp)
                        layer._gpath = gp
                else:
                    p = ld.get("path")
                    if not p:
                        skipped.append(ld.get("name", "?"))
                        continue
                    src = VideoSource(p)
                    layer = Layer(ld.get("name", "video"), source=src)
                layer.enabled = ld.get("enabled", True)
                layer.opacity = ld.get("opacity", 1.0)
                layer.blend = ld.get("blend", "normal")
                layer.start = ld.get("start", 0.0)
                layer.trim_in = ld.get("trim_in", 0.0)
                layer.duration = ld.get("duration")
                layer.chain = Chain().load(ld.get("chain", {}))
                if ld.get("warp"):
                    layer.warp = TimeWarp().load(ld["warp"])
                self.timeline.layers.append(layer)
            except Exception as e:               # skip a bad layer, keep loading
                skipped.append(f"{ld.get('name', '?')} ({e})")
        vl = next((l for l in self.timeline.layers if not l.is_granular and l.source), None)
        if vl:
            self._detect_beats(vl.source.path)
        self._reprepare_and_audio()
        self._rebuild_warps()
        self._refresh_layer_list()
        self.play_btn.setEnabled(bool(self.timeline.layers))
        self.render_btn.setEnabled(bool(self.timeline.layers))
        if skipped:
            QtWidgets.QMessageBox.warning(
                self, "Open project", "Skipped layers:\n- " + "\n- ".join(skipped))
        self.status.showMessage(f"Loaded {path}")

    def closeEvent(self, e):
        self.audio_player.stop()
        if self.live_cam is not None:
            self.live_cam.close()
        if self.live_audio_env is not None:
            self.live_audio_env.stop()
        if self.input_hub is not None:
            self.input_hub.stop()
            self.input_hub.wait(500)
        for l in self.timeline.layers:
            if l.source:
                l.source.release()
        super().closeEvent(e)
